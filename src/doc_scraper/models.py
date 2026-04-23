from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ErrorRecord:
    query_id: str
    error_message: str


@dataclass
class DocRecord:
    query_id: str
    doc_number: Optional[str] = None
    entity_name: Optional[str] = None
    entity_id: Optional[str] = None
    address: Optional[str] = None
    district: Optional[str] = None
    city: Optional[str] = None
    validity: Optional[str] = None
    status: Optional[str] = None
    category: Optional[str] = None
    audience: Optional[str] = None
    owner: Optional[str] = None
    operator: Optional[str] = None
    raw_fields: dict = field(default_factory=dict)

    def to_row(self) -> dict:
        return {
            "Query ID": self.query_id,
            "Doc Number": self.doc_number,
            "Entity Name": self.entity_name,
            "Entity ID": self.entity_id,
            "Address": self.address,
            "District": self.district,
            "City": self.city,
            "Validity": self.validity,
            "Status": self.status,
            "Category": self.category,
            "Audience": self.audience,
            "Owner": self.owner,
            "Operator": self.operator,
        }
