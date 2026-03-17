import json
import re
from pathlib import Path
from typing import Dict


class ExhibitMapping:
    def __init__(self, mapping_json_path: str):
        self.mapping_path = Path(mapping_json_path)
        data = json.loads(self.mapping_path.read_text(encoding="utf-8"))
        self.object_name_to_exhibit: Dict[str, str] = data.get("object_name_to_exhibit", {})
        self.exhibit_to_object_name: Dict[str, str] = data.get("exhibit_to_object_name", {})
        self.aoi_aliases: Dict[str, str] = data.get("aoi_aliases", {})

    def normalize_object_name(self, object_name: str) -> str:
        if not object_name:
            return object_name

        candidate = object_name.strip()
        if candidate in self.object_name_to_exhibit or candidate in self.exhibit_to_object_name:
            return candidate

        if "_AoI_" in candidate:
            candidate = candidate.split("_AoI_")[0]
            if candidate in self.object_name_to_exhibit or candidate in self.exhibit_to_object_name:
                return candidate

        match = re.match(r"^([A-D]\d)", candidate)
        if match:
            short_name = match.group(1)
            if short_name in self.object_name_to_exhibit:
                return short_name

        return candidate

    def to_exhibit_key(self, exhibit_or_object: str) -> str:
        """Accept RL exhibit key or Unity/Neo4j object names and return RL exhibit key."""
        normalized = self.normalize_object_name(exhibit_or_object)
        if normalized in self.exhibit_to_object_name:
            return normalized
        if normalized in self.object_name_to_exhibit:
            return self.object_name_to_exhibit[normalized]
        raise ValueError(
            f"Unknown exhibit/object '{exhibit_or_object}' (normalized='{normalized}'). "
            f"Expected one of objectName={sorted(self.object_name_to_exhibit)} "
            f"or exhibit={sorted(self.exhibit_to_object_name)}"
        )

    def normalize_aoi(self, aoi_name: str) -> str:
        return self.aoi_aliases.get(aoi_name, aoi_name)



