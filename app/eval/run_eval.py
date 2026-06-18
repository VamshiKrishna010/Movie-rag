from .dataset import DATA
from app.generate import generate


def run():
    results = []
    for item in DATA:
        q = item["q"]
        expected = item["a"]
        pred = generate(q)
        results.append({"q": q, "expected": expected, "pred": pred})
    return results
