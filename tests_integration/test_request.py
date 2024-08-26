import requests

if __name__ == "__main__":
    res = requests.get("https://pypi.org/pypi/pydantic/json").json()
    print(res)
