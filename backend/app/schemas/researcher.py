from pydantic import BaseModel


class ResearcherOut(BaseModel):
    id: str
    name: str
    institution: str | None
    country: str | None
    lat: float | None
    lng: float | None
    citations: int
    h_index: int
    works_count: int
    recent_papers: int
    field: str | None
    umap_x: float | None
    umap_y: float | None
    openalex_url: str | None
    topics: list[str] | None = None

    model_config = {"from_attributes": True}
