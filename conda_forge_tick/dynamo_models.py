"""The ORM for DynamoDB for the autotick bot"""
import uuid

from pynamodb.models import Model
from pynamodb.attributes import (
    UnicodeAttribute, NumberAttribute,
)


class PRJson(Model):
    class Meta:
        table_name = "pr_json"

    id = NumberAttribute(hash_key=True)
    state = UnicodeAttribute()
    ETag = UnicodeAttribute()
    merged_at = UnicodeAttribute()

    @classmethod
    def dump(cls, pr_json: dict):
        """Dumps a PR JSON object to DynamoDB"""
        attrs = dict(id=pr_json["id"], state=pr_json["state"], merged_at=pr_json["merged_at"],)
        if not isinstance(attrs["id"], int):
            attrs["id"] = -uuid.UUID(attrs["id"]).int
        if "ETag" in pr_json:
            attrs["ETag"] = pr_json["ETag"]
        item = cls(**attrs)
        item.save()
