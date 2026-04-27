#!/bin/bash
# =============================================================================
# launch.sh - EC2 인스턴스를 생성하고 CS 논문 수집 파이프라인을 자동 실행
#
# 사용법:
#   ./launch.sh
#
# 환경변수:
#   RESULTS_BUCKET  - 결과 저장 S3 버킷 (기본: researcherworld-papers-{timestamp})
#   INSTANCE_TYPE   - EC2 인스턴스 타입 (기본: t3.xlarge)
#   KEY_NAME        - EC2 key pair 이름 (없으면 새로 생성)
# =============================================================================
set -euo pipefail

REGION="us-east-1"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
RESULTS_BUCKET="${RESULTS_BUCKET:-researcherworld-papers-${TIMESTAMP}}"
INSTANCE_TYPE="${INSTANCE_TYPE:-t3.large}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== ResearcherWorld CS Papers Collection Pipeline ==="
echo "RESULTS_BUCKET: ${RESULTS_BUCKET}"
echo "INSTANCE_TYPE:  ${INSTANCE_TYPE}"
echo "REGION:         ${REGION}"
echo ""

# -----------------------------------------------------------
# 1. S3 버킷 생성 (존재하지 않으면)
# -----------------------------------------------------------
echo "[1/5] S3 버킷 확인/생성..."
if ! aws s3api head-bucket --bucket "${RESULTS_BUCKET}" --region "${REGION}" 2>/dev/null; then
    aws s3api create-bucket \
        --bucket "${RESULTS_BUCKET}" \
        --region "${REGION}" \
        > /dev/null
    echo "  -> 버킷 생성 완료: ${RESULTS_BUCKET}"
else
    echo "  -> 기존 버킷 사용: ${RESULTS_BUCKET}"
fi

# -----------------------------------------------------------
# 2. 수집 스크립트를 S3에 업로드
# -----------------------------------------------------------
echo "[2/5] collect_papers.py를 S3에 업로드..."
aws s3 cp "${SCRIPT_DIR}/collect_papers.py" "s3://${RESULTS_BUCKET}/collect_papers.py" \
    --region "${REGION}" > /dev/null
echo "  -> 업로드 완료"

# -----------------------------------------------------------
# 3. Key Pair 처리
# -----------------------------------------------------------
if [ -z "${KEY_NAME:-}" ]; then
    KEY_NAME="researcherworld-collect-${TIMESTAMP}"
    echo "[3/5] Key Pair 생성: ${KEY_NAME}..."
    aws ec2 create-key-pair \
        --key-name "${KEY_NAME}" \
        --region "${REGION}" \
        --query 'KeyMaterial' \
        --output text > "${SCRIPT_DIR}/${KEY_NAME}.pem"
    chmod 400 "${SCRIPT_DIR}/${KEY_NAME}.pem"
    echo "  -> Key 저장: ${SCRIPT_DIR}/${KEY_NAME}.pem"
else
    echo "[3/5] 기존 Key Pair 사용: ${KEY_NAME}"
fi

# -----------------------------------------------------------
# 4. IAM Instance Profile 확인
# -----------------------------------------------------------
echo "[4/5] EC2 설정 준비..."

# Amazon Linux 2023 최신 AMI 조회
AMI_ID=$(aws ec2 describe-images \
    --region "${REGION}" \
    --owners amazon \
    --filters "Name=name,Values=al2023-ami-2023*-x86_64" \
              "Name=state,Values=available" \
    --query 'sort_by(Images, &CreationDate)[-1].ImageId' \
    --output text)
echo "  -> AMI: ${AMI_ID}"

# -----------------------------------------------------------
# 5. EC2 인스턴스 생성
# -----------------------------------------------------------
echo "[5/5] EC2 인스턴스 생성..."

AWS_KEY=$(aws configure get aws_access_key_id)
AWS_SECRET=$(aws configure get aws_secret_access_key)
USERDATA_FILE=$(mktemp /tmp/userdata_XXXXXX.sh)

cat > "${USERDATA_FILE}" << EOF
#!/bin/bash
exec > /tmp/collect.log 2>&1
set -x

export AWS_ACCESS_KEY_ID=${AWS_KEY}
export AWS_SECRET_ACCESS_KEY=${AWS_SECRET}
export AWS_DEFAULT_REGION=us-east-1

echo "[1] Installing pip..."
yum install -y python3-pip
echo "[2] Installing boto3..."
pip3 install boto3
echo "[3] Downloading collect script..."
aws s3 cp s3://${RESULTS_BUCKET}/collect_papers.py /tmp/collect_papers.py
echo "[4] Starting collection..."
python3 /tmp/collect_papers.py --bucket ${RESULTS_BUCKET}
echo "[5] Done. Shutting down..."
shutdown -h now
EOF

INSTANCE_ID=$(aws ec2 run-instances \
    --region "${REGION}" \
    --image-id "${AMI_ID}" \
    --instance-type "${INSTANCE_TYPE}" \
    --key-name "${KEY_NAME}" \
    --security-group-ids sg-0aff227e8ddb77230 \
    --user-data "file://${USERDATA_FILE}" \
    --instance-initiated-shutdown-behavior terminate \
    --block-device-mappings "[{\"DeviceName\":\"/dev/xvda\",\"Ebs\":{\"VolumeSize\":30,\"VolumeType\":\"gp3\",\"DeleteOnTermination\":true}}]" \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=researcherworld-collect-${TIMESTAMP}},{Key=Project,Value=ResearcherWorld}]" \
    --query 'Instances[0].InstanceId' \
    --output text)

rm -f "${USERDATA_FILE}"

echo ""
echo "=========================================="
echo "  EC2 인스턴스 시작 완료!"
echo "=========================================="
echo ""
echo "  Instance ID:    ${INSTANCE_ID}"
echo "  Instance Type:  ${INSTANCE_TYPE}"
echo "  Results Bucket: ${RESULTS_BUCKET}"
echo "  Key Pair:       ${KEY_NAME}"
echo ""
echo "  진행 확인:"
echo "    aws s3 ls s3://${RESULTS_BUCKET}/"
echo ""
echo "  로그 확인 (SSH 접속 후):"
echo "    ssh -i ${KEY_NAME}.pem ec2-user@<public-ip>"
echo "    tail -f /tmp/collect.log"
echo ""
echo "  완료 확인:"
echo "    aws s3 ls s3://${RESULTS_BUCKET}/done.txt"
echo ""
echo "  완료 후 import 실행:"
echo "    ./import.sh ${RESULTS_BUCKET}"
echo "=========================================="
