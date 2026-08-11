from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


class KnowledgeBase:
    def __init__(self, base_dir: Optional[Path] = None):
        root = Path(base_dir) if base_dir else Path(__file__).resolve().parents[1]
        knowledge_dir = root / "knowledge"
        self.kg_path = knowledge_dir / "museum_knowledge_graph.json"
        self.mapping_path = knowledge_dir / "object_aoi_mapping.json"

        self._kg = self._load_json(self.kg_path)
        self._mapping = self._load_json(self.mapping_path)

        self.exhibits: Dict[str, Dict[str, Any]] = self._kg.get("exhibits", {})
        self.aois: Dict[str, Dict[str, Any]] = self._kg.get("aois", {})
        self.exhibit_aoi_mapping: Dict[str, List[str]] = self._kg.get("exhibit_aoi_mapping", {})
        self.object_name_to_exhibit: Dict[str, str] = self._mapping.get("object_name_to_exhibit", {})
        self.exhibit_to_object_name: Dict[str, str] = self._mapping.get("exhibit_to_object_name", {})
        self.aoi_aliases: Dict[str, str] = self._mapping.get("aoi_aliases", {})

    @staticmethod
    def _load_json(path: Path) -> Dict[str, Any]:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def normalize_object_name(self, object_name: Optional[str]) -> Optional[str]:
        if not object_name:
            return object_name

        candidate = str(object_name).strip()
        if candidate in self.object_name_to_exhibit or candidate in self.exhibit_to_object_name:
            return candidate

        if "_AoI_" in candidate:
            candidate = candidate.split("_AoI_")[0]
            if candidate in self.object_name_to_exhibit or candidate in self.exhibit_to_object_name:
                return candidate

        if len(candidate) >= 2 and candidate[0] in {"A", "B", "C", "D"} and candidate[1].isdigit():
            short_name = candidate[:2]
            if short_name in self.object_name_to_exhibit:
                return short_name

        return candidate

    def normalize_aoi_name(self, aoi_name: Optional[str]) -> Optional[str]:
        if not aoi_name:
            return aoi_name
        candidate = str(aoi_name).strip()
        return self.aoi_aliases.get(candidate, candidate)

    def to_exhibit_key(self, exhibit_or_object: Optional[str]) -> Optional[str]:
        if not exhibit_or_object:
            return exhibit_or_object
        normalized = self.normalize_object_name(exhibit_or_object)
        if normalized in self.exhibit_to_object_name:
            return normalized
        return self.object_name_to_exhibit.get(normalized)

    def get_object_by_name(self, object_name: Optional[str]) -> Optional[Dict[str, Any]]:
        exhibit_key = self.to_exhibit_key(object_name)
        if not exhibit_key:
            return None
        exhibit = self.exhibits.get(exhibit_key)
        if exhibit is None:
            return None
        return {"exhibit_key": exhibit_key, **exhibit}

    def get_aoi_by_name(self, aoi_name: Optional[str]) -> Optional[Dict[str, Any]]:
        normalized = self.normalize_aoi_name(aoi_name)
        if not normalized:
            return None
        return self.aois.get(normalized)

    def get_object_image(self, object_name: Optional[str]) -> Optional[str]:
        exhibit = self.get_object_by_name(object_name)
        if not exhibit:
            return None
        return exhibit.get("img")

    def get_object_context(self, object_name: Optional[str]) -> Optional[Dict[str, Any]]:
        exhibit = self.get_object_by_name(object_name)
        if not exhibit:
            return None
        return {
            "object_name": exhibit.get("object_name"),
            "painting_name": exhibit.get("painting_name"),
            "description": exhibit.get("description"),
            "more_info": exhibit.get("more_info"),
            "artist": exhibit.get("artist"),
            "year": exhibit.get("year"),
            "location": exhibit.get("location"),
            "style": exhibit.get("style"),
            "period": exhibit.get("period"),
            "img": exhibit.get("img"),
            "aois": exhibit.get("aois", []),
        }

    def get_aoi_context(self, aoi_name: Optional[str]) -> Optional[Dict[str, Any]]:
        aoi = self.get_aoi_by_name(aoi_name)
        if not aoi:
            return None
        return {
            "name": aoi.get("name"),
            "description": aoi.get("description"),
        }

    def get_graph_data(self) -> Dict[str, Any]:
        return {
            "exhibits": self.exhibits,
            "aois": self.aois,
            "exhibit_aoi_mapping": self.exhibit_aoi_mapping,
            "summary": self._kg.get("summary", {}),
        }
