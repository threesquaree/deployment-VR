"""
Simple Knowledge Graph - Clean, non-duplicate fact loading
"""

import json
from typing import Dict, List, Optional, Tuple

class SimpleKnowledgeGraph:
    """Clean exhibit -> facts mapping with proper AOI relationships"""
    
    def __init__(self, json_path: str = None):
        self.exhibit_facts: Dict[str, List[str]] = {}
        self.exhibit_aois: Dict[str, List[str]] = {}
        self.exhibit_metadata: Dict[str, dict] = {}
        
        if json_path:
            self._load_from_json(json_path)
    
    def _load_from_json(self, json_path: str):
        """Load exhibits and facts cleanly - NO DUPLICATES"""
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        exhibits = data.get("exhibits", {})
        aois_data = data.get("aois", {})
        
        for exhibit_name, exhibit_data in exhibits.items():
            self.exhibit_metadata[exhibit_name] = exhibit_data
            self.exhibit_aois[exhibit_name] = exhibit_data.get("aois", [])
            facts = self._build_clean_facts(exhibit_data)
            facts_with_ids = self._generate_fact_ids(exhibit_name, facts)
            self.exhibit_facts[exhibit_name] = facts_with_ids
    
    def _build_clean_facts(self, exhibit_data: dict) -> List[str]:
        """Build a clean list of unique facts for an exhibit"""
        facts = []
        
        if "description" in exhibit_data:
            facts.append(exhibit_data["description"])
        
        if "more_info" in exhibit_data:
            facts.append(exhibit_data["more_info"])
        
        if "artist" in exhibit_data and "year" in exhibit_data:
            facts.append(f"The artwork was created by {exhibit_data['artist']} in {exhibit_data['year']}")
        
        if "location" in exhibit_data:
            facts.append(f"The artwork is located at {exhibit_data['location']}")
        
        if "style" in exhibit_data:
            facts.append(f"Style: {exhibit_data['style']}")
        
        if "artist" in exhibit_data and "year" not in exhibit_data:
            facts.append(f"Artist: {exhibit_data['artist']}")
        
        return facts
    
    def _generate_fact_ids(self, exhibit_name: str, facts: List[str]) -> List[str]:
        """Generate clean IDs and embed them in fact text"""
        prefix = ''.join([c for c in exhibit_name if c.isupper()])[:2]
        if len(prefix) < 2:
            prefix = exhibit_name[:2].upper()
        
        facts_with_ids = []
        for i, fact in enumerate(facts, 1):
            fact_id = f"{prefix}_{i:03d}"
            fact_with_id = f"[{fact_id}] {fact}"
            facts_with_ids.append(fact_with_id)
        
        return facts_with_ids

    def get_exhibit_names(self) -> List[str]:
        return list(self.exhibit_facts.keys())
    
    def get_exhibit_facts(self, exhibit_name: str) -> List[str]:
        return self.exhibit_facts.get(exhibit_name, [])
    
    def get_exhibit_aois(self, exhibit_name: str) -> List[str]:
        return self.exhibit_aois.get(exhibit_name, [])
    
    def get_exhibit_metadata(self, exhibit_name: str) -> dict:
        return self.exhibit_metadata.get(exhibit_name, {})
    
    def get_total_facts_count(self) -> int:
        return sum(len(facts) for facts in self.exhibit_facts.values())
    
    def get_all_fact_ids(self) -> set:
        """Return set of all valid fact IDs across all exhibits."""
        fact_ids = set()
        for facts in self.exhibit_facts.values():
            for fact in facts:
                fact_id = self.extract_fact_id(fact)
                if fact_id:
                    fact_ids.add(fact_id)
        return fact_ids
    
    def get_exhibit_summary(self) -> Dict[str, dict]:
        summary = {}
        for exhibit_name in self.exhibit_facts:
            summary[exhibit_name] = {
                "fact_count": len(self.exhibit_facts[exhibit_name]),
                "aoi_count": len(self.exhibit_aois[exhibit_name]),
                "aois": self.exhibit_aois[exhibit_name]
            }
        return summary
    
    @staticmethod
    def extract_fact_id(fact_with_id: str) -> str:
        if fact_with_id.startswith('[') and ']' in fact_with_id:
            return fact_with_id[1:fact_with_id.index(']')]
        return ""
    
    @staticmethod
    def strip_fact_id(fact_with_id: str) -> str:
        if fact_with_id.startswith('[') and ']' in fact_with_id:
            return fact_with_id[fact_with_id.index(']')+1:].strip()
        return fact_with_id
    
    def print_structure(self):
        print("\n" + "="*80)
        print("KNOWLEDGE GRAPH STRUCTURE")
        print("="*80)
        
        total_facts = 0
        total_aois = 0
        
        for exhibit_name in sorted(self.exhibit_facts.keys()):
            facts = self.exhibit_facts[exhibit_name]
            aois = self.exhibit_aois[exhibit_name]
            
            total_facts += len(facts)
            total_aois += len(aois)
            
            print(f"\n[*] {exhibit_name}")
            print(f"    Facts: {len(facts)} | AOIs: {len(aois)}")
            aoilist = ', '.join(aois) if aois else 'None'
            print(f"    AOI List: {aoilist}")
            print(f"    Facts:")
            for fact in facts:
                fact_id = self.extract_fact_id(fact)
                fact_text = self.strip_fact_id(fact)
                print(f"       {fact_id}: {fact_text}")
        
        print("\n" + "="*80)
        print(f"TOTALS: {len(self.exhibit_facts)} exhibits | {total_facts} facts | {total_aois} AOIs")
        print("="*80 + "\n")

