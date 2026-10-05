import csv, json, re, sys
from collections import Counter
from datetime import datetime
from decimal import Decimal

from rdflib import Graph, Literal, Namespace
from rdflib.namespace import RDF, RDFS, XSD

EX = Namespace("http://example.org/mkr/")

def parse_date(s):
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Невідомий формат дати: {s!r}")

def load_data(path):
    flights = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            row = {k.strip(): (v or "").strip() for k, v in row.items()}
            fid = row["flight_id"].upper()
            rec = {
                "id": fid,
                "airline": row["airline"],
                "from_city": row["from_city"].title(),
                "from_country": row["from_country"],
                "to_city": row["to_city"].title(),
                "to_country": row["to_country"],
                "date": parse_date(row["dep_date"]),
                "duration": int(row["duration_min"]),
                "price": row["price_eur"],
                "note": row["note"],
            }
            if fid in flights:
                old = flights[fid]
                for k, v in rec.items():
                    if old.get(k) in ("", None):
                        old[k] = v
            else:
                flights[fid] = rec
    return flights


def init_schema(g):
    classes = ["Flight", "Airline", "City", "Country"]
    flight_subclasses = ["BudgetFlight", "LongFlight"]
    for c in classes:
        g.add((EX[c], RDF.type, RDFS.Class))
    for c in flight_subclasses:
        g.add((EX[c], RDF.type, RDFS.Class))
        g.add((EX[c], RDFS.subClassOf, EX.Flight))

    props = {
        "operatedBy":      (EX.Flight, EX.Airline),
        "departsFrom":     (EX.Flight, EX.City),
        "arrivesAt":       (EX.Flight, EX.City),
        "locatedIn":       (EX.City, EX.Country),
        "departureDate":   (EX.Flight, XSD.date),
        "durationMin":     (EX.Flight, XSD.integer),
        "priceEur":        (EX.Flight, XSD.decimal),
        "hasDelayMinutes": (EX.Flight, XSD.integer),
        "reportedBy":      (RDF.Statement, RDFS.Resource),
        "fromBusyCountry": (EX.Flight, XSD.boolean),
    }

    for name, (dom, rng) in props.items():
        p = EX[name]
        g.add((p, RDF.type, RDF.Property))
        g.add((p, RDFS.domain, dom))
        g.add((p, RDFS.range, rng))


def iri(kind, name):
    """ex:<kind>/<name>, пробіли -> '_'."""
    return EX[f"{kind}/{re.sub(r'\s+', '_', name.strip())}"]


def parse_note(note):
    result = {}
    for part in note.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            result[k.strip().lower()] = v.strip()
    return result


def build_graph(flights, params):
    g = Graph()
    g.bind('ex', EX)
    g.bind('rdf', RDF)
    g.bind('rdfs', RDFS)
    g.bind('xsd', XSD)
    init_schema(g)

    budget_max = Decimal(str(params["budget_threshold_eur"]))
    long_min = int(params["long_flight_min"])

    dep_count = Counter(r["from_country"] for r in flights.values())

    def add_place(city, country):
        c, k = iri("city", city), iri("country", country)
        g.add((c, RDF.type, EX.City))
        g.add((c, RDFS.label, Literal(city, lang="en")))
        g.add((c, EX.locatedIn, k))
        g.add((k, RDF.type, EX.Country))
        g.add((k, RDFS.label, Literal(country, lang="en")))
        return c

    for fid, r in flights.items():
        f = iri("flight", fid)

        airline = iri("airline", r["airline"])
        g.add((airline, RDF.type, EX.Airline))
        g.add((airline, RDFS.label, Literal(r["airline"], lang="en")))
        g.add((f, EX.operatedBy, airline))

        g.add((f, EX.departsFrom, add_place(r["from_city"], r["from_country"])))
        g.add((f, EX.arrivesAt, add_place(r["to_city"], r["to_country"])))

        g.add((f, EX.departureDate, Literal(r["date"].isoformat(), datatype=XSD.date)))
        g.add((f, EX.durationMin, Literal(r["duration"], datatype=XSD.integer)))
        has_price = r["price"] != ""
        if has_price:
            g.add((f, EX.priceEur, Literal(r["price"], datatype=XSD.decimal)))

        is_budget = has_price and Decimal(r["price"]) <= budget_max
        is_long = r["duration"] >= long_min
        if is_budget:
            g.add((f, RDF.type, EX.BudgetFlight))
        if is_long:
            g.add((f, RDF.type, EX.LongFlight))
        if not (is_budget or is_long):
            g.add((f, RDF.type, EX.Flight))

        note = parse_note(r["note"])
        if "delay" in note:
            st = EX[f"stmt/{fid}-delay"]
            g.add((st, RDF.type, RDF.Statement))
            g.add((st, RDF.subject, f))
            g.add((st, RDF.predicate, EX.hasDelayMinutes))
            g.add((st, RDF.object, Literal(int(note["delay"]), datatype=XSD.integer)))
            if note.get("by"):
                g.add((st, EX.reportedBy, iri("source", note["by"])))

        if dep_count[r["from_country"]] >= 2:
            g.add((f, EX.fromBusyCountry, Literal(True, datatype=XSD.boolean)))

    return g


def main():
    csv_path, params_path, out = sys.argv[1:]

    with open(params_path, encoding="utf-8") as f:
        params = json.load(f)

    flights = load_data(csv_path)
    g = build_graph(flights, params)
    g.serialize(destination=out, format='turtle')

if __name__ == "__main__":
    main()