"""
This script is used for dabbling into IDMP Ontologies
"""

from rdflib import Graph, URIRef
from rdflib.namespace import RDF, RDFS, OWL, SKOS
from collections import Counter

g = Graph().parse(rdf_file_path, format="xml")

count = 0
for s, p, o in g:
    if count > 100:
        break
    print(f"Subject: {s}")
    print(f"Predicate: {p}")
    print(f"Object: {o}")
    print(100*"-")
    count += 1

print(f"Number of triplets: {len(g)}")


# all namespaces
for i, item in enumerate(g.namespaces()):
    prefix, namespace = item
    print(f"{prefix} → {namespace}")
print(f"Numer of namespaces: {i}")

# counting entities with type declaration
type_counts = Counter()
objects = []
for s, p, o in g.triples((None, RDF.type, None)):
    objects.append(o)
    object_type = o.split("/")[-1].split("#")[-1]
    type_counts[object_type] += 1

print(f"Unique types: {list(type_counts.keys())}")

print("Top 10 entity types:")
for entity_type, count in type_counts.most_common(10):
    print(f"  {entity_type:40s} : {count:5d} instances")


# finding classes
classes = list(g.subjects(RDF.type, OWL.Class))

for i, cls in enumerate(classes):
    class_name = cls.split('/')[-1].split('#')[-1]
    print(f"{i:2d}. {class_name}")
    
# Get only named classes
named_classes = [c for c in g.subjects(RDF.type, OWL.Class) if isinstance(c, URIRef)]