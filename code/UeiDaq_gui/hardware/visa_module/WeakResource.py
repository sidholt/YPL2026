from typing import Dict, Set

from pyvisa import Resource


class WeakResource(dict):
    def __init__(self, *args, **kwargs):
        self.resources: Dict[str, Resource] = {}
        self.resource_to_id: Dict[str, Set[str]] = {}
        self.id_to_resource: Dict[str, str] = {}
        super().__init__(*args, **kwargs)

    def __getitem__(self, resource_name):
        return self.resources[resource_name]

    def __contains__(self, resource_name):
        return resource_name in self.resources

    def __setitem__(self, key, value):
        raise Exception("Cannot set item in WeakResource")

    def __delitem__(self, key):
        raise Exception("Cannot delete item from WeakResource")

    def add_id(self, id_, resource: Resource):
        id_ = str(id_)
        if id_ in self.id_to_resource:
            raise Exception(f"ID {id_} already exists in WeakResource")

        resource_name = resource.resource_name
        if resource_name not in self.resource_to_id:
            self.resource_to_id[resource_name] = set()

        if resource_name in self.resources and self.resources[resource_name] != resource:
            raise Exception(f"Resource {resource_name} does not match existing resource")

        self.id_to_resource[id_] = resource_name
        self.resources[resource_name] = resource
        self.resource_to_id[resource_name].add(id_)

    def remove_id(self, id_):
        id_ = str(id_)
        if id_ not in self.id_to_resource:
            return

        resource_name = self.id_to_resource[id_]
        self.resource_to_id[resource_name].remove(id_)
        self.id_to_resource.pop(id_)

        self.garbage_collect()

    def get_resource_from_id(self, id_):
        id_ = str(id_)
        if id_ not in self.id_to_resource:
            raise Exception(f"ID {id_} not found in WeakResource")

        return self.resources[self.id_to_resource[id_]]

    def __del__(self):
        for resource_name in self.resources:
            self.resources[resource_name].close()

    def garbage_collect(self):
        for resource in list(self.resources.values()):
            resource_name = resource.resource_name

            if len(self.resource_to_id[resource_name]) == 0:
                self.resources[resource_name].close()
                self.resources.pop(resource_name)
                self.resource_to_id.pop(resource_name)
