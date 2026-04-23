from pydantic import BaseModel, Field, model_validator
from typing import Literal, Union

from typing import Literal, get_args

type PossibleGraphTypes = Literal["bar", "line", "section"]
graph_types_list = list(get_args(PossibleGraphTypes))

type PossibleAggregationType = Literal["count", "sum", "avg"]
aggregation_type_list = list(get_args(PossibleAggregationType))

class AggregationColumn(BaseModel):
    column_name: str
    aggregation_type: PossibleAggregationType

class GraphJSON(BaseModel):
    table: str
    graph_type: PossibleGraphTypes
    x: str | AggregationColumn
    y: str | AggregationColumn

    @model_validator(mode="after")
    def exactly_one_agg(self):
        x_is_agg = isinstance(self.x, AggregationColumn)
        y_is_agg = isinstance(self.y, AggregationColumn)
        if x_is_agg and y_is_agg: 
            raise ValueError("x and y cannot both be aggregations (sum, avg, count), there must be <= 1.")
        return self
