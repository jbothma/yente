import logging
from typing import TYPE_CHECKING, Any, AsyncGenerator, Dict, List, Optional, Tuple
from elasticsearch import TransportError
from nomenklatura.loader import Loader
from followthemoney.schema import Schema
from followthemoney.proxy import EntityProxy
from followthemoney.types import registry

from yente.settings import ES_INDEX
from yente.entity import Dataset, Entity
from yente.index import get_es
from yente.data import get_datasets
from yente.mapping import TEXT_TYPES

if TYPE_CHECKING:
    from yente.loader import IndexLoader

log = logging.getLogger(__name__)


def filter_query(
    shoulds,
    dataset: Dataset,
    schema: Optional[Schema] = None,
    filters: Dict[str, List[str]] = {},
):
    filterqs = [{"terms": {"datasets": dataset.source_names}}]
    if schema is not None:
        schemata = schema.matchable_schemata
        schemata.add(schema)
        if not schema.matchable:
            schemata.update(schema.descendants)
        names = [s.name for s in schemata]
        filterqs.append({"terms": {"schema": names}})
    for field, values in filters.items():
        values = [v for v in values if len(v)]
        if len(values):
            filterqs.append({"terms": {field: values}})
    return {"bool": {"filter": filterqs, "should": shoulds, "minimum_should_match": 1}}


def entity_query(dataset: Dataset, entity: EntityProxy, fuzzy: bool = False):
    terms: Dict[str, List[str]] = {}
    texts: List[str] = []
    shoulds: List[Dict[str, Any]] = []
    for prop, value in entity.itervalues():
        if prop.type == registry.name:
            query = {
                "match_phrase": {
                    "names": {
                        "query": value,
                        "slop": 3,
                        # "fuzziness": 1,
                        "boost": 3.0,
                        # "lenient": True,
                    }
                }
            }
            shoulds.append(query)
        if prop.type.group is not None:
            if prop.type not in TEXT_TYPES:
                field = prop.type.group
                if field not in terms:
                    terms[field] = []
                terms[field].append(value)
        texts.append(value)

    for field, texts in terms.items():
        shoulds.append({"terms": {field: texts}})
    for text in texts:
        shoulds.append({"match_phrase": {"text": text}})
    return filter_query(shoulds, dataset, schema=entity.schema)


def text_query(
    dataset: Dataset,
    query: str,
    schema: Optional[Schema] = None,
    filters: Dict[str, List[str]] = {},
    fuzzy: bool = False,
):

    if query is None or not len(query.strip()):
        should = {"match_all": {}}
    else:
        should = {
            "query_string": {
                "query": query,
                # "default_field": "text",
                "fields": ["names^3", "text"],
                "default_operator": "and",
                "fuzziness": 2 if fuzzy else 0,
                "lenient": fuzzy,
            }
        }
    return filter_query([should], dataset, schema=schema, filters=filters)


def facet_aggregations(fields: List[str] = []) -> Dict[str, Any]:
    aggs = {}
    for field in fields:
        aggs[field] = {"terms": {"field": field, "size": 1000}}
    return aggs


def result_entity(datasets, data) -> Tuple[Optional[Entity], float]:
    source = data.get("_source")
    if source is None:
        return None, 0.0
    source["id"] = data.get("_id")
    return Entity.from_data(source, datasets), data.get("_score")


async def result_entities(result) -> AsyncGenerator[Tuple[Entity, float], None]:
    datasets = await get_datasets()
    hits = result.get("hits", {})
    for hit in hits.get("hits", []):
        entity, score = result_entity(datasets, hit)
        if entity is not None:
            yield entity, score


async def query_entities(query: Dict[Any, Any], limit: int = 5):
    # pprint(query)
    es = await get_es()
    resp = await es.search(index=ES_INDEX, query=query, size=limit)
    async for entity, score in result_entities(resp):
        yield entity, score


async def query_results(
    loader: "IndexLoader",
    query: Dict[Any, Any],
    limit: int,
    nested: bool = False,
    offset: Optional[int] = None,
    aggregations: Optional[Dict] = None,
):
    results = []
    resp = await loader.es.search(
        index=ES_INDEX,
        query=query,
        size=limit,
        from_=offset,
        aggregations=aggregations,
    )
    async for result, score in result_entities(resp):
        if not nested:
            data = result.to_dict()
        else:
            data = await result.to_nested_dict(loader)
        data["score"] = score
        results.append(data)
    hits = resp.get("hits", {})
    total = hits.get("total")
    facets = {}
    for field, agg in resp.get("aggregations", {}).items():
        facets[field] = {"label": field, "values": []}
        # print(field, agg)
        for bucket in agg.get("buckets", []):
            key = bucket.get("key")
            value = {"name": key, "label": key, "count": bucket.get("doc_count")}
            if field == "datasets":
                facets[field]["label"] = "Data sources"
                value["label"] = loader.datasets[key].title
            if field in registry.groups:
                type_ = registry.groups[field]
                facets[field]["label"] = type_.plural
                value["label"] = type_.caption(key)
            facets[field]["values"].append(value)
    return {
        "results": results,
        "facets": facets,
        "total": total.get("value"),
        "limit": limit,
        "offset": offset,
    }


async def get_index_stats() -> Dict[str, Any]:
    es = await get_es()
    stats = await es.indices.stats(index=ES_INDEX)
    return stats.get("indices", {}).get(ES_INDEX)


async def get_index_status() -> bool:
    es = await get_es()
    try:
        health = await es.cluster.health(index=ES_INDEX)
        return health.get("status") in ("yellow", "green")
    except TransportError:
        return False