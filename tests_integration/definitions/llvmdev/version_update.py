from fastapi import APIRouter

router = APIRouter()


@router.get("/pypi.org/pypi/pydantic/json")
def handle():
    return {
        "new_version": "1.8.2",
    }


def prepare():
    pass
