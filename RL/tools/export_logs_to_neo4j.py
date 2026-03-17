import argparse
import json
from pathlib import Path


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def build_cypher(records):
    statements = []
    for record in records:
        if record.get("record_type") != "interaction":
            continue
        session_id = record["session_id"]
        timestamp = record["timestamp"]
        reply_text = json.dumps(record.get("reply_text", ""))
        user_text = json.dumps(record.get("user_text", ""))
        current_object = json.dumps(record.get("current_object_name"))
        action = json.dumps(record.get("action"))
        option_name = json.dumps(record.get("option"))
        subaction = json.dumps(record.get("subaction"))
        statements.append(
            "MERGE (s:RLSession {session_id: %s}) "
            "MERGE (t:RLTurn {session_id: %s, timestamp: %s}) "
            "SET t.user_text = %s, t.reply_text = %s, t.current_object_name = %s, "
            "t.action = %s, t.option = %s, t.subaction = %s "
            "MERGE (s)-[:HAS_TURN]->(t);" % (
                json.dumps(session_id),
                json.dumps(session_id),
                json.dumps(timestamp),
                user_text,
                reply_text,
                current_object,
                action,
                option_name,
                subaction,
            )
        )
    return statements


def main():
    parser = argparse.ArgumentParser(description="Export RL JSONL logs to a Neo4j-friendly .cypher file.")
    parser.add_argument("--input", required=True, help="Path to a session JSONL log file.")
    parser.add_argument("--output", required=True, help="Output .cypher file path.")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    statements = build_cypher(iter_jsonl(input_path))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(statements) + "\n", encoding="utf-8")
    print(f"Wrote {len(statements)} statements to {output_path}")


if __name__ == "__main__":
    main()
