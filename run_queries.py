import csv, json, re, time
from datetime import datetime, timezone
from pathlib import Path
import requests

ENDPOINT = "https://query.wikidata.org/sparql"
HEADERS = {
    "User-Agent": "mkr1/1.0",
    "Accept": "application/sparql-results+json",
}
BASE = Path(__file__).resolve().parent
MIN_Q1_ROWS = 5


def run_query(query, retries=4):
    for attempt in range(retries):
        resp = requests.post(ENDPOINT, data={"query": query},
                             headers=HEADERS, timeout=90)
        if resp.status_code == 200:
            data = resp.json()
            cols = data["head"]["vars"]
            rows = [{c: b.get(c, {}).get("value", "") for c in cols}
                    for b in data["results"]["bindings"]]
            return cols, rows
        if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries - 1:
            wait = int(resp.headers.get("Retry-After", 5 * (attempt + 1)))
            time.sleep(wait)
            continue
        resp.raise_for_status()
    raise RuntimeError("Failed to run query")


def write_csv(path, cols, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def halve_threshold(query):
    m = re.search(r"FILTER\(\?v > ([\d.]+)\)", query)
    new = float(m.group(1)) / 2
    new_str = str(int(new)) if new == int(new) else str(new)
    return query[:m.start(1)] + new_str + query[m.end(1):], new_str


def main():
    results, notes = {}, []

    for name in ("q1", "q2", "q3"):
        qpath = BASE / f"{name}.rq"
        query = qpath.read_text(encoding="utf-8")
        cols, rows = run_query(query)

        if name == "q1" and len(rows) < MIN_Q1_ROWS:
            query, new_thr = halve_threshold(query)
            qpath.write_text(query, encoding="utf-8")
            time.sleep(1)
            cols, rows = run_query(query)
            notes.append(f"Примітка: Q1 повернув менше {MIN_Q1_ROWS} рядків, "
                         f"поріг зменшено вдвічі до {new_thr}.")

        write_csv(BASE / f"{name}.csv", cols, rows)
        results[name] = rows
        print(f"{name}: {len(rows)} рядків")
        time.sleep(1)

    retrieved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (BASE / "meta.json").write_text(
        json.dumps({"retrieved_at": retrieved_at}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    q1, q2, q3 = (results[k][0] if results[k] else None for k in ("q1", "q2", "q3"))
    lines = [
        f"Q1: {q1['itemLabel']}, {q1['value']}",
        f"Q2: {q2['regionLabel']}, {q2['cnt']}",
        f"Q3: {q3['population']}",
    ] + notes
    (BASE / "ANSWERS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
