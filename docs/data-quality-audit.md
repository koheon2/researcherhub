# Data Quality Audit

이 문서는 ResearcherHub의 OpenAlex 기반 논문/연구자 데이터에 대한 1차 정합성 조사 기록이다. 조사는 로컬 DB 원본을 수정하지 않고 read-only 쿼리와 공개 외부 API 대조만으로 수행했다.

조사 목적은 “무엇이 얼마나 틀렸는지”와 “어떤 정보는 어느 정도 믿을 수 있는지”를 구분해, 이후 quality-filtered product layer 설계의 기준을 정하는 것이다.

## 요약

현재 데이터는 전체 원천 저장소로는 가치가 있지만, 제품 지표에 그대로 쓰기에는 오염이 크다. 특히 CS/AI 분석 대상이 아닌 record, repository/dataset metadata, OpenAlex topic mismatch가 섞여 있다.

핵심 판단:

- 원본 DB는 보존한다.
- 제품 지표는 quality-filtered layer를 거쳐 계산해야 한다.
- 연구자의 current/last-known institution은 국가/기관 비교 기준으로 쓰지 않는다.
- 국가/기관 비교는 publication-time affiliation 기준을 유지한다.
- publication-time affiliation은 coverage를 명시해야 한다.

## 전체 DB 계량

### Paper Type 분포

`papers`에는 article 외에도 dataset, book, dissertation, libguides 등 비논문성 record가 많이 포함되어 있다.

| type | rows |
| --- | ---: |
| article | 13,463,090 |
| dataset | 2,760,727 |
| other | 2,627,321 |
| book-chapter | 1,447,343 |
| preprint | 1,104,565 |
| dissertation | 807,265 |
| libguides | 306,289 |
| book | 300,728 |
| report | 85,367 |
| review | 67,691 |

해석: “논문 DB”라고 부르기에는 비논문성 record가 크다. 제품 화면에서 논문 수, 트렌드, progress를 계산할 때 `type` 기준 필터가 필요하다.

### 연도 이상치

| condition | count |
| --- | ---: |
| `year > 2026` | 265 |
| `year < 1900` | 121,305 |

미래 연도는 대부분 Zenodo/Mendeley Data 같은 repository metadata에서 전파된 것으로 보인다. 1900년 이전 record는 실제 고문헌/디지털 컬렉션인 경우가 있으나 CS/AI 연구 분석 대상은 아니다.

### DOI / Source Bucket

| bucket | papers | future year | old year | missing abstract |
| --- | ---: | ---: | ---: | ---: |
| other DOI | 14,041,259 | 114 | 20,904 | 4,690,727 |
| no DOI | 8,247,042 | 26 | 100,057 | 3,960,874 |
| Zenodo | 725,364 | 85 | 83 | 55,132 |
| Figshare | 87,446 | 0 | 0 | 4,211 |
| Mendeley Data | 17,254 | 40 | 0 | 267 |
| Heidelberg Digital | 6,366 | 0 | 261 | 6,362 |

해석: DOI가 있어도 Crossref 논문 record라는 뜻은 아니다. DataCite 기반 repository DOI가 많이 섞여 있으며, 이들은 별도 bucket으로 다루는 것이 안전하다.

### Abstract / DOI / Affiliation Coverage

- abstract 보유율은 샘플 기준 약 62.3%다.
- DOI 보유율은 샘플 기준 약 64.3%다.
- `paper_authors` 원천 row는 35,744,826개다.
- 원천 `paper_authors`에서 기관 결측은 약 14.16M row다.
- 원천 `paper_authors`에서 국가 결측은 약 14.31M row다.
- `paper_author_affiliations`는 기관/국가가 있는 row만 backfill한 21.43M row 레이어다.

해석: publication-time affiliation layer는 비교 기준으로 적절하지만, 전체 authorship coverage는 약 60% 수준이다. UI와 리포트에서 coverage/provenance를 드러내야 한다.

## 외부 대조 결과

### 분층 Paper Audit 439개

표본 구성:

- normal recent article: 120
- future-year paper: 80
- old-year paper: 80
- repository/dataset: 80
- AI facet paper: 79

이 표본은 일부러 이상치와 repository record를 많이 포함한 분층 표본이다. 전체 DB 비율로 직접 해석하면 안 된다.

| class | count | ratio |
| --- | ---: | ---: |
| problematic | 255 | 58.1% |
| consistent enough | 103 | 23.5% |
| minor issue | 51 | 11.6% |
| external missing | 30 | 6.8% |

주요 flag:

| flag | count | ratio |
| --- | ---: | ---: |
| likely non-research or repository | 142 | 32.3% |
| topic suspicious | 126 | 28.7% |
| pre-1900 year | 80 | 18.2% |
| future year | 78 | 17.8% |
| year mismatch | 62 | 14.1% |
| external missing | 30 | 6.8% |

대조 provider:

| provider | count |
| --- | ---: |
| DataCite | 249 |
| Crossref | 160 |
| missing | 30 |

### 최근 Article Audit 300개

조건:

- `year` between 2017 and 2026
- `type = article`
- DOI 있음

| class | count | ratio |
| --- | ---: | ---: |
| external missing | 195 | 65.0% |
| consistent enough | 63 | 21.0% |
| problematic | 35 | 11.7% |
| minor issue | 7 | 2.3% |

외부 대조 provider:

| provider | count | ratio |
| --- | ---: | ---: |
| missing | 195 | 65.0% |
| Crossref | 69 | 23.0% |
| DataCite | 36 | 12.0% |

외부에서 확인된 105개만 기준으로 보면:

| class | count | ratio among resolved |
| --- | ---: | ---: |
| consistent enough | 63 | 60.0% |
| problematic | 35 | 33.3% |
| minor issue | 7 | 6.7% |

주의: `external missing`은 Crossref/DataCite에서 바로 확인하지 못했다는 뜻이지 곧바로 오류라는 뜻은 아니다. DOI prefix나 등록기관 편향이 있을 수 있다. 다만 제품에서 “검증된 논문”으로 보기에는 불확실하다.

### Researcher Audit 60명

OpenAlex author API와 로컬 `researchers` row를 대조했다.

| class | count | ratio |
| --- | ---: | ---: |
| consistent enough | 47 | 78.3% |
| major issue | 7 | 11.7% |
| metric drift | 6 | 10.0% |

주요 flag:

| flag | count | ratio |
| --- | ---: | ---: |
| last-known institution mismatch | 7 | 11.7% |
| citation drift > 5% | 6 | 10.0% |
| last-known country mismatch | 5 | 8.3% |
| works drift > 5% | 5 | 8.3% |
| h-index drift | 1 | 1.7% |

해석: citation, works, h-index는 OpenAlex의 업데이트에 따라 drift가 있지만 대체로 일관된다. 반면 last-known institution/country는 약 10%대에서 불일치가 나타나므로 국가/기관 비교 기준으로 쓰면 안 된다.

## 대표 사례

### Zenodo Future Year Metadata

DB row:

- DOI: [`10.5281/zenodo.2574643`](https://doi.org/10.5281/zenodo.2574643)
- title: `Hub genes in a pan-cancer co-expression network show potential for predicting drug responses`
- DB year: 2050
- DB type: article

DataCite/Zenodo metadata도 issued date를 2050으로 제공한다. 즉 DB import만의 오류가 아니라 원천 metadata 이상치가 전파된 케이스다. 제품 지표에서는 future year flag로 제외해야 한다.

### Mendeley Data Dataset

DB row:

- DOI: [`10.17632/zznzb2pt2p.1`](https://doi.org/10.17632/zznzb2pt2p.1)
- title: `Decabromodiphenyl ether impaired the self-renewal and differentiation of spermatogonial stem cells...`
- DB year: 2036
- DB type: dataset

DataCite 기준 resource type도 dataset이다. CS/AI 논문 분석 대상이 아니라 repository/dataset bucket으로 분리해야 한다.

### Heidelberg Digital Old Work

DB row:

- DOI: [`10.11588/diglit.45311`](https://doi.org/10.11588/diglit.45311)
- title: `Concordia curatorum:// & fratrum mendicantiu[m]//`
- DB year: 1503

Heidelberg University Library의 디지털 고문헌 record다. 연도 자체는 맞지만 CS/AI 연구 논문이 아니다. old year 필터만으로 “오류”라고 삭제하면 안 되고, 분석 대상 제외로 다뤄야 한다.

### 정상 Crossref Proceedings Article

DB row:

- DOI: [`10.1063/5.0161992`](https://doi.org/10.1063/5.0161992)
- title: `Smart suspect tracker using deep learning model`
- DB year: 2023

Crossref 기준 2023 proceedings article로 확인된다. 이런 record는 현재 DB와 외부 metadata가 잘 맞는 정상 케이스다.

## 제품 판단

지금 데이터는 “전체 원천 저장소”로 보관할 가치는 있지만, 제품 지표에 직접 쓰면 왜곡된다. 우선 다음 기준의 quality-filtered layer가 필요하다.

1. `1900 <= year <= current_year`
2. article/proceedings/preprint/review 등 연구 문헌 중심 type allowlist
3. dataset, software, database, libguides, paratext, retraction, erratum 등 별도 bucket 또는 제외
4. Zenodo, Mendeley Data, Figshare 같은 repository DOI는 무조건 버리지 말고 provenance와 type으로 분리
5. OpenAlex topic/aboutness만으로 CS/AI 판단하지 않기
6. 세부 AI facet은 title + abstract 기반 weak label로 유지하되 confidence/provenance를 표시
7. 국가/기관 비교는 publication-time affiliation 기준 유지
8. researcher current/last-known institution은 비교 지표에 사용하지 않기
9. affiliation coverage를 summary/API/UI에 명시

## 적용된 Quality Filter 결과

Milestone 2.4에서 conservative v0 품질 필터를 비파괴 방식으로 적용했다. 원본 `papers` row는 삭제하거나 수정하지 않고, `paper_quality_flags`에 flag/provenance를 저장한다.

제품 summary/API는 `exclude` severity가 붙은 paper를 제외한다. `warning` severity는 제품 지표에서 제외하지 않고, 후속 보정과 provenance 대상으로 유지한다.

적용 결과:

| 항목 | count |
| --- | ---: |
| total flag rows | 16,725,095 |
| flagged papers | 12,247,290 |
| excluded papers | 3,223,432 |
| `publication_country_year_stats` rows | 10,642 |

Flag 분포:

| severity | flag type | count |
| --- | --- | ---: |
| exclude | `excluded_type` | 3,102,255 |
| exclude | `future_year` | 265 |
| exclude | `pre_1900_year` | 121,305 |
| warning | `missing_abstract` | 8,717,573 |
| warning | `repository_doi` | 830,064 |
| warning | `suspicious_openalex_topic` | 3,953,633 |

운영 판단:

- `future_year`, `pre_1900_year`, excluded paper type은 제품 지표에서 제외한다.
- repository DOI와 missing abstract는 전체 제외하지 않는다.
- OpenAlex topic mismatch는 warning으로 남기고, 다음 taxonomy/ROR 보정 단계의 입력으로 쓴다.
- 국가별 연도 progress는 `publication_country_year_stats` summary를 사용해 대형 join timeout을 피한다.

## 남은 조사/구현 과제

- DOI prefix/provider별 coverage와 error rate를 materialized summary로 계산
- 표본 외부 대조 결과를 CSV로 저장할 수 있는 audit workflow 추가
- ambiguous/unmatched 상위 기관에 대한 alias curation 또는 ROR API fallback
- warning flag를 UI/API provenance로 더 명확히 노출

## 적용된 Institution Normalization 결과

Milestone 2.5에서 로컬 OpenAlex institutions snapshot과 ROR dump 기반 publication-time 기관 정규화 v0를 적용했다. 원본 `paper_author_affiliations.institution_name`은 보존하고, `institution_name_matches` mapping layer를 summary refresh 시 join한다.

적용 결과:

| 항목 | count |
| --- | ---: |
| distinct institution/country pairs | 63,985 |
| matched pairs | 63,707 |
| ambiguous pairs | 209 |
| unmatched pairs | 69 |
| matched affiliation rows | 21,352,995 |
| affiliation rows with ROR match | 21,352,995 |

대표 smoke match:

| raw institution | country | canonical | ROR |
| --- | --- | --- | --- |
| Massachusetts Institute of Technology | US | Massachusetts Institute of Technology | `042nb2s44` |
| Stanford University | US | Stanford University | `00f54p054` |
| Korea Advanced Institute of Science and Technology | KR | Korea Advanced Institute of Science and Technology | `05apxxy63` |
| Seoul National University | KR | Seoul National University | `04h9pn542` |
