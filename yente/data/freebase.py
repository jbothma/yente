from typing import Dict, List, Optional
from pydantic import BaseModel, Field
from pydantic.networks import AnyHttpUrl
from followthemoney import model
from followthemoney.proxy import EntityProxy
from followthemoney.schema import Schema
from followthemoney.property import Property

from yente import settings
from yente.data.common import ScoredEntityResponse


class FreebaseType(BaseModel):
    id: str = Field(..., example="Person")
    name: str = Field(..., example="People")
    description: Optional[str] = Field(None, example="...")

    @classmethod
    def from_schema(cls, schema: Schema) -> "FreebaseType":
        desc = schema.description or schema.label
        return cls(id=schema.name, name=schema.plural, description=desc)


class FreebaseProperty(BaseModel):
    id: str = Field(..., example="birthDate")
    name: str = Field(..., example="Date of birth")
    description: Optional[str] = Field(None, example="...")

    @classmethod
    def from_prop(cls, prop: Property) -> "FreebaseProperty":
        return cls(id=prop.qname, name=prop.label, description=prop.description)


class FreebaseEntity(BaseModel):
    id: str = Field(..., example="NK-A7z....")
    name: str = Field(..., example="John Doe")
    description: Optional[str] = Field(None, example="...")
    type: List[FreebaseType]

    @classmethod
    def from_proxy(cls, proxy: EntityProxy):
        type_ = [FreebaseType.from_schema(proxy.schema)]
        return FreebaseEntity(id=proxy.id, name=proxy.caption, type=type_)


class FreebaseScoredEntity(FreebaseEntity):
    score: Optional[float] = Field(..., example=0.99)
    match: Optional[bool] = Field(..., example=False)

    @classmethod
    def from_scored(cls, data: ScoredEntityResponse) -> "FreebaseScoredEntity":
        schema = model.get(data.schema_)
        if schema is None:
            raise RuntimeError("Missing schema: %s" % data.schema_)
        return cls(
            id=data.id,
            name=data.caption,
            type=[FreebaseType.from_schema(schema)],
            score=data.score,
            match=data.match,
        )


class FreebaseResponse(BaseModel):
    code: str = "/api/status/ok"
    status: str = "200 OK"


class FreebaseSuggestResponse(FreebaseResponse):
    prefix: str


class FreebaseTypeSuggestResponse(FreebaseSuggestResponse):
    result: List[FreebaseType]


class FreebaseEntitySuggestResponse(FreebaseSuggestResponse):
    result: List[FreebaseEntity]


class FreebasePropertySuggestResponse(FreebaseSuggestResponse):
    result: List[FreebaseProperty]


class FreebaseManifestView(BaseModel):
    url: str


class FreebaseManifestPreview(BaseModel):
    url: str
    width: int
    height: int


class FreebaseManifestSuggestType(BaseModel):
    service_url: AnyHttpUrl
    service_path: str


class FreebaseManifestSuggest(BaseModel):
    entity: FreebaseManifestSuggestType
    type: FreebaseManifestSuggestType
    property: FreebaseManifestSuggestType


class FreebaseManifest(BaseModel):
    versions: List[str] = Field(..., example=["0.2"])
    name: str = Field(..., example=settings.TITLE)
    identifierSpace: AnyHttpUrl
    schemaSpace: AnyHttpUrl
    view: FreebaseManifestView
    preview: FreebaseManifestPreview
    suggest: FreebaseManifestSuggest
    defaultTypes: List[FreebaseType]


class FreebaseEntityResult(BaseModel):
    result: List[FreebaseScoredEntity]


FreebaseQueryResult = Dict[str, FreebaseEntityResult]
