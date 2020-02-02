"""The ORM for DynamoDB for the autotick bot"""
import uuid

from pynamodb.models import Model
from pynamodb.attributes import (
    UnicodeAttribute,
    NumberAttribute,
)


class PRJson(Model):
    class Meta:
        table_name = "pr_json"
        region = "us-east-2"

    id = NumberAttribute(hash_key=True)
    state = UnicodeAttribute()
    ETag = UnicodeAttribute(null=True)
    merged_at = UnicodeAttribute(null=True)

    @classmethod
    def dump(cls, pr_json: dict):
        """Dumps a PR JSON object to DynamoDB"""
        attrs = dict(
            id=pr_json["id"],
            state=pr_json["state"],
            merged_at=pr_json.get("merged_at"),
            ETag=pr_json.get("ETag"),
        )
        if not isinstance(attrs["id"], int):
            attrs["id"] = -uuid.UUID(attrs["id"]).int
        item = cls(**attrs)
        item.save()
