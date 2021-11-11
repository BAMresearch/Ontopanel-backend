import rdflib
import pandas as pd
import os
from rdflib.util import get_tree
import json
from rest_framework.exceptions import APIException


class ImportOnto:
    def __init__(self, filepath, inputType):
        self.filepath = filepath
        self.inputType = inputType
        self.g = rdflib.Graph()
        self.base_onto = None
        # {namespace:prefix}
        self.namespace_list = {}
        self.imported_ontology = []
        self.entity_tree = {}
        self.deprected = []
        self.anno_properties = {rdflib.OWL.backwardCompatibleWith,
                                rdflib.OWL.deprecated,
                                rdflib.OWL.incompatibleWith,
                                rdflib.OWL.priorVersion,
                                rdflib.OWL.versionInfo,
                                rdflib.RDFS.comment,
                                rdflib.RDFS.isDefinedBy,
                                rdflib.RDFS.seeAlso}
        self.df = pd.DataFrame(
            [],
            columns=(
                "EntityName",
                "BelongsTo",
                "RDFLabel",
                "SpecialInfo",
                "Color",
                "namespace",
            ),
        )

    def get_imports(self, address, keyword="URL"):
        try:
            if keyword != "URL":
                parse_format = rdflib.util.guess_format(address.name)
            else:
                parse_format = rdflib.util.guess_format(address)

            if parse_format:
                parse_format_list = [
                    parse_format,
                    "xml",
                    "turtle",
                    "html",
                    "hturtle",
                    "n3",
                    "nquads",
                    "trix",
                    "rdfa",
                ]
            else:
                parse_format_list = [
                    "xml",
                    "turtle",
                    "html",
                    "hturtle",
                    "n3",
                    "nquads",
                    "trix",
                    "rdfa",
                ]

            t = rdflib.Graph()
            if keyword != "URL":
                address_data = address.read()

            for i in range(len(parse_format_list)):
                try:
                    if keyword != "URL":
                        t.parse(data=address_data, format=parse_format_list[i])
                        self.g.parse(data=address_data,
                                     format=parse_format_list[i])
                    else:
                        t.parse(address, format=parse_format_list[i])
                        self.g.parse(address, format=parse_format_list[i])

                    namespaces = list(self.g.namespaces())
                    for ns_prefix, namespace in namespaces:

                        if namespace not in self.namespace_list.keys():
                            if ns_prefix == "":
                                ns_prefix = "base"
                                self.g.bind("base", namespace)
                            self.namespace_list[namespace] = ns_prefix

                    break
                except Exception as e:
                    print(e)
                    pass
            if i == len(parse_format_list) - 1:
                raise APIException(
                    "Your ontology or it imported ontologies can not be parsed. Tried to merge ontologies first in xml or turtle.")

            if list(t.triples((None, rdflib.OWL.imports, None))):
                for _, _, o in t.triples((None, rdflib.OWL.imports, None)):
                    if o not in self.imported_ontology:
                        self.get_imports(o)
                        self.imported_ontology.append(o)

        except Exception as e:

            raise APIException(
                "There is something wrong in parsing. Please use merged ontologies in xml or turtle.")

    def compute_n3(self, entity, includeLabel=True):
        if type(entity) != rdflib.BNode:
            prefix, namespace, name = self.g.compute_qname(entity)
            if namespace not in self.namespace_list:
                self.namespace_list[namespace] = prefix
                # sub_n3 = self.g.namespace_manager.qname(sub)
            n3 = self.namespace_list[namespace] + ":" + name
            # prefix_short = sub_n3.split(':')[0]

            rdfLabel = self.g.label(entity).strip()
            if includeLabel and rdfLabel and (rdfLabel != name):

                n3 = n3 + "(" + rdfLabel + ")"
        else:
            n3 = None

        return n3

    def assign_df(self, sub, belongsTo):

        if type(sub) != rdflib.BNode:

            prefix, namespace, name = self.g.compute_qname(sub)

            sub_n3 = self.compute_n3(sub, includeLabel=False)

            # get annotations
            annotations = {}
            color = 'none'

            for anno in self.anno_properties:
                anno_list = list(self.g.objects(subject=sub, predicate=anno))
                # see anno property used multi times
                if anno_list:
                    anno_list_n3 = []
                    if anno == rdflib.OWL.deprecated:

                        if anno_list[0].value == True:
                            self.deprected.append(sub)

                    for j in anno_list:
                        try:
                            anno_list_n3.append(j.n3())
                        except Exception:
                            anno_list_n3.append(j)

                    anno_prop_n3 = self.compute_n3(anno)
                    annotations[anno_prop_n3] = anno_list_n3

            if belongsTo == "Class":
                subClassOf = [
                    self.compute_n3(x)
                    for x in self.g.objects(
                        subject=sub, predicate=rdflib.RDFS.subClassOf
                    )
                ]

                equivalentTo = [
                    self.compute_n3(x)
                    for x in self.g.objects(
                        subject=sub, predicate=rdflib.OWL.equivalentClass
                    ) if type(x) != rdflib.BNode
                ]

                disjointWith = [
                    self.compute_n3(x)
                    for x in self.g.objects(
                        subject=sub, predicate=rdflib.OWL.disjointWith
                    )
                ]

                cco = rdflib.Namespace(
                    'http://www.ontologyrepository.com/CommonCoreOntologies/')
                bfo = rdflib.Namespace('http://purl.obolibrary.org/obo/')

                if sub in list(self.g.transitive_subjects(object=bfo.BFO_0000015, predicate=rdflib.RDFS.subClassOf)):

                    color = 'green'
                elif sub in list(self.g.transitive_subjects(object=cco.InformationContentEntity, predicate=rdflib.RDFS.subClassOf)):

                    color = 'yellow'

                elif sub in list(self.g.transitive_subjects(object=cco.InformationBearingArtifact, predicate=rdflib.RDFS.subClassOf)):

                    color = 'grey'

                SpecialInfo = {
                    "SubClassOf": subClassOf,
                    "EquivalentTo": equivalentTo,
                    "DisjointWith": disjointWith}

            elif belongsTo == "OP":
                subPropertyOf = [
                    self.compute_n3(x)
                    for x in self.g.objects(
                        subject=sub, predicate=rdflib.RDFS.subPropertyOf
                    )
                ]
                inverseOf = [
                    self.compute_n3(x)
                    for x in self.g.objects(subject=sub, predicate=rdflib.OWL.inverseOf)
                ]
                disjointWith = [
                    self.compute_n3(x)
                    for x in self.g.objects(
                        subject=sub, predicate=rdflib.OWL.disjointWith
                    )
                ]
                domain = [
                    self.compute_n3(x)
                    for x in self.g.objects(subject=sub, predicate=rdflib.RDFS.domain)
                ]
                range_op = [
                    self.compute_n3(x)
                    for x in self.g.objects(subject=sub, predicate=rdflib.RDFS.range)
                ]

                equivalentTo = [
                    self.compute_n3(x)
                    for x in self.g.objects(
                        subject=sub, predicate=rdflib.OWL.equivalentProperty
                    ) if type(x) != rdflib.BNode
                ]

                SpecialInfo = {
                    "SubPropertyOf": subPropertyOf,
                    "EquivalentTo": equivalentTo,
                    "DisjointWith": disjointWith,
                    "InverseOf": inverseOf,
                    "Domain": domain,
                    "Range": range_op,
                }

            elif belongsTo == "DP":
                subPropertyOf = [
                    self.compute_n3(x)
                    for x in self.g.objects(
                        subject=sub, predicate=rdflib.RDFS.subPropertyOf
                    )
                ]
                disjointWith = [
                    self.compute_n3(x)
                    for x in self.g.objects(
                        subject=sub, predicate=rdflib.OWL.disjointWith
                    )
                ]
                domain = [
                    self.compute_n3(x)
                    for x in self.g.objects(subject=sub, predicate=rdflib.RDFS.domain)
                ]
                range_op = [
                    self.compute_n3(x)
                    for x in self.g.objects(subject=sub, predicate=rdflib.RDFS.range)
                ]
                equivalentTo = [
                    self.compute_n3(x)
                    for x in self.g.objects(
                        subject=sub, predicate=rdflib.OWL.equivalentProperty
                    ) if type(x) != rdflib.BNode
                ]

                SpecialInfo = {
                    "SubPropertyOf": subPropertyOf,
                    "EquivalentTo": equivalentTo,
                    "DisjointWith": disjointWith,
                    "Domain": domain,
                    "Range": range_op,
                }

            elif belongsTo == "AP":
                subPropertyOf = [
                    self.compute_n3(x)
                    for x in self.g.objects(
                        subject=sub, predicate=rdflib.RDFS.subPropertyOf
                    )
                ]
                SpecialInfo = {
                    "SubPropertyOf": subPropertyOf,
                }

            else:
                type_ind = [
                    self.compute_n3(x)
                    for x in self.g.objects(subject=sub, predicate=rdflib.RDF.type)
                ]
                SpecialInfo = {"Type": type_ind}

            new_row = {
                'Color': color,
                "EntityName": sub_n3,
                "RDFLabel": self.g.label(sub),
                "Annotations": annotations,
                "SpecialInfo": SpecialInfo,
                "BelongsTo": belongsTo,
                "namespace": namespace,
            }

        else:
            new_row = None

        return new_row

    def extract_anno_properties(self):
        self.anno_properties.update(
            set(self.g.subjects(
                predicate=rdflib.RDF.type, object=rdflib.OWL.AnnotationProperty
            ))
        )

    def extract_infos(self):
        extract_entity = {
            rdflib.OWL.Class: "Class",
            rdflib.OWL.ObjectProperty: "OP",
            rdflib.OWL.DatatypeProperty: "DP",
            rdflib.OWL.AnnotationProperty: "AP",
        }

        i = 0
        for entity in extract_entity.keys():
            for s, _, _ in self.g.triples((None, rdflib.RDF.type, entity)):
                new_row = self.assign_df(s, extract_entity[entity])
                if new_row:
                    self.df = self.df.append(new_row, ignore_index=True)
                if entity == rdflib.OWL.Class:
                    for s_in, _, _ in self.g.triples((None, rdflib.RDF.type, s)):
                        new_row = self.assign_df(s_in, "Individual")
                        if new_row:
                            self.df = self.df.append(
                                new_row, ignore_index=True)

    def map_function(self, x):

        n3 = self.compute_n3(x, includeLabel=False)
        if x in self.deprected:
            return f'<del>{n3}</del>'

        return n3

    def find_roots(self, prop, obj):
        roots = []

        all_entities = set(self.g.subjects(
            predicate=rdflib.RDF.type, object=obj))
        for i in all_entities:
            if type(i) != rdflib.BNode:
                root_level = list(self.g.objects(subject=i, predicate=prop))

                if (not root_level) or (
                    (root_level[0] not in all_entities)
                    and (type(root_level[0])) != rdflib.BNode
                ):

                    tree = get_tree(
                        self.g,
                        i,
                        prop,
                        mapper=self.map_function,
                        sortkey=lambda s: (s[0].startswith('<del>'), s[0])
                    )
                    roots.append(tree)

        return sorted(roots, key=lambda s: (s[0].startswith('<del>'), s[0]))

    def get_roots(self):
        entity_type = {
            "Class": [rdflib.RDFS.subClassOf, rdflib.OWL.Class],
            "OP": [rdflib.RDFS.subPropertyOf, rdflib.OWL.ObjectProperty],
            "DP": [rdflib.RDFS.subPropertyOf, rdflib.OWL.DatatypeProperty],
            "AP": [rdflib.RDFS.subPropertyOf, rdflib.OWL.AnnotationProperty],
        }

        for key, value in entity_type.items():
            self.entity_tree[key] = self.find_roots(value[0], value[1])

        # inidvidual, has no tree structure
        Inds = sorted(
            self.df[self.df["BelongsTo"] ==
                    "Individual"]["EntityName"].tolist()
        )
        self.entity_tree["Individual"] = [(x, []) for x in Inds]

    def run_all(self):
        if self.inputType == "URL":
            self.get_imports(self.filepath)
        else:
            self.get_imports(self.filepath, keyword="file")

        self.extract_anno_properties()
        self.extract_infos()
        self.get_roots()

        used_namespaces = self.df["namespace"].unique()

        output_namespace = [
            f"{self.namespace_list[x]}:{x}" for x in used_namespaces
        ]

        self.df = (
            self.df.sort_values(by=["Color", "EntityName"])
            .drop(["namespace"], axis=1)
            .drop_duplicates(subset="EntityName")
            .set_index("EntityName")
        )

        return self.df, output_namespace, self.entity_tree


def onto_to_table(filepath, inputType="URL"):
    import_onto = ImportOnto(filepath, inputType=inputType)
    df, output_namespace, tree = import_onto.run_all()

    df = df.to_json(orient="index")

    return df, output_namespace, tree


if __name__ == "__main__":
    filepath = r"https://raw.githubusercontent.com/Mat-O-Lab/MSEO/main/MSEO_mid.owl"
    df, output_namespace, tree = onto_to_table(filepath)
    with open(
        r"C:\Users\ychen2\Documents\Project\javascript\Vue\drawioPlugin\vanilla\onto_file.json",
        "w",
    ) as f:
        json.dump({'title': "MESO", 'onto_source': filepath, 'onto_table': {"table": df, "tree": tree,
                  "namespace": output_namespace}, 'author': 'no author'}, f)