from pydantic import BaseModel


class TableMetadata(BaseModel):
    table: str
    record_name: str
    fields: list[str]
    all_fields: list[str] | None


class KpitenProfile(BaseModel):
    name: str
    tables: list[TableMetadata]
