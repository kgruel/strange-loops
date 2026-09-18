"""Read-only comparison of historical tick-window commitments.

Run within the project venv. The output contains counts, coordinates, and
comparison booleans only; row payloads, identifiers, and keys are never saved.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from engine.arrival_projection import rows_of_record
from engine.canonical_audit import _ChainWalkArrival, _ChainWalkJsonl
from engine.jsonl_codec import deserialize_records
from engine.row_commitment import fact_row_hash

ROOT = Path('/Users/kaygee/Code/loops-rehearsals/loops-20260918-171627')
RAW = ROOT / 'input/project.jsonl'
PREPARED = ROOT / 'prepared/project.jsonl'
ARRIVAL = ROOT / 'fresh-rehearsal-run-2/stores/01M2VCBPYRT63W2FKA54PVKP7D.arrival'
OUTPUT = ROOT / 'fresh-rehearsal-run-2/window-diagnostic.json'


def inspect(path: Path, *, arrival: bool = False):
    walk = _ChainWalkArrival() if arrival else _ChainWalkJsonl()
    facts, ticks = [], []
    line_count = 0
    with path.open('rb') as stream:
        for line_count, raw in enumerate(stream, 1):
            if arrival:
                record = json.loads(raw)
                coordinate = record['ord']
                rows = rows_of_record(record)
            else:
                coordinate = line_count
                rows = deserialize_records(raw.decode('utf-8'))
            for kind, row in rows:
                walk.feed(coordinate, kind, row)
                (facts if kind == 'fact' else ticks).append((coordinate, row))
    return walk, facts, ticks, line_count


def safe_breaks(walk):
    result = []
    for text in walk._breaks:
        match = re.search(r'(?:line|ordinal) (\d+).*?: (.*)$', text)
        result.append({
            'coordinate': int(match.group(1)) if match else None,
            'reason': match.group(2) if match else 'unparsed',
        })
    return result


def main():
    stages = {
        'raw': inspect(RAW),
        'prepared': inspect(PREPARED),
        'arrival': inspect(ARRIVAL, arrival=True),
    }
    report = {}
    for name, (walk, facts, ticks, lines) in stages.items():
        report[name] = {
            'record_count': lines,
            'fact_count': len(facts),
            'tick_count': len(ticks),
            'chain_ok': walk.verdict().ok,
            'first_breaks': safe_breaks(walk),
            'chained_tick_count': walk._chained,
        }

    raw_facts, prepared_facts, arrival_facts = (
        stages[name][1] for name in ('raw', 'prepared', 'arrival')
    )
    raw_ticks, prepared_ticks, arrival_ticks = (
        stages[name][2] for name in ('raw', 'prepared', 'arrival')
    )
    arrival_hashes = {fact_row_hash(row) for _, row in arrival_facts}
    fact_pairs = list(zip(raw_facts, prepared_facts, strict=True))
    tick_pairs = list(zip(raw_ticks, prepared_ticks, strict=True))
    report['mapping'] = {
        'fact_rows_changed_hash': sum(
            fact_row_hash(a) != fact_row_hash(b)
            for (_, a), (_, b) in fact_pairs
        ),
        'same_fact_ids_and_order': all(a[0] == b[0] for (_, a), (_, b) in fact_pairs),
        'tick_rows_identical': all(a == b for (_, a), (_, b) in tick_pairs),
        'only_observer_changed': all(
            a[:3] == b[:3] and a[4:] == b[4:]
            for (_, a), (_, b) in fact_pairs
        ),
    }
    prepared_ticks_by_id = {row[0]: row for _, row in prepared_ticks}
    report['migration'] = {
        'historic_tick_rows_identical': all(
            row == prepared_ticks_by_id.get(row[0])
            for _, row in arrival_ticks if row[0] in prepared_ticks_by_id
        ),
        'historic_tick_count_in_target': sum(
            row[0] in prepared_ticks_by_id for _, row in arrival_ticks
        ),
        'extra_tick_count': sum(
            row[0] not in prepared_ticks_by_id for _, row in arrival_ticks
        ),
        'prepared_fact_hashes_present': sum(
            fact_row_hash(row) in arrival_hashes for _, row in prepared_facts
        ),
    }

    raw_walk, prepared_walk, arrival_walk = (
        stages[name][0] for name in ('raw', 'prepared', 'arrival')
    )
    raw_ticks_by_id = {row[0]: (coordinate, row) for coordinate, row in raw_ticks}
    prepared_ticks_by_id = {
        row[0]: (coordinate, row) for coordinate, row in prepared_ticks
    }
    failures = []
    for coordinate, row in arrival_ticks:
        if row[0] not in prepared_ticks_by_id or row[9] is None:
            continue
        arrival_hash = arrival_walk._window_hash(row[7], row[8])
        if arrival_hash == row[9]:
            continue
        raw_coordinate, raw_row = raw_ticks_by_id[row[0]]
        prepared_coordinate, prepared_row = prepared_ticks_by_id[row[0]]
        raw_hash = raw_walk._window_hash(raw_row[7], raw_row[8])
        prepared_hash = prepared_walk._window_hash(
            prepared_row[7], prepared_row[8]
        )
        failures.append({
            'arrival_ordinal': coordinate,
            'raw_line': raw_coordinate,
            'prepared_line': prepared_coordinate,
            'raw_window_ok': raw_hash == raw_row[9],
            'prepared_window_ok': prepared_hash == prepared_row[9],
            'arrival_window_ok': False,
            'raw_vs_prepared_window_hash_equal': raw_hash == prepared_hash,
            'prepared_vs_arrival_window_hash_equal': prepared_hash == arrival_hash,
        })
    report['historic_failed_windows'] = failures
    OUTPUT.write_text(json.dumps(report, indent=2) + '\n')
    os.chmod(OUTPUT, 0o600)
    print(json.dumps({
        'raw_chain_ok': report['raw']['chain_ok'],
        'prepared_chain_ok': report['prepared']['chain_ok'],
        'arrival_chain_ok': report['arrival']['chain_ok'],
        'failed_historic_windows': len(failures),
    }))


if __name__ == '__main__':
    main()
