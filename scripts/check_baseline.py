"""Verify existing IDs, translation inputs, overrides and historical machine output survive expansion."""
import json
import sqlite3
from pathlib import Path
from atlas.storage import ROOT,connect,hydrate,enrichment_hash,write_json,now


def main():
    folder=ROOT/'.runtime/full-coverage'
    baseline=json.loads((folder/'baseline.json').read_text())
    old=sqlite3.connect(folder/'atlas-before-full-coverage.sqlite3');old.row_factory=sqlite3.Row
    missing,changed,translations,overrides=[],[],[],[]
    with connect() as db:
        for identifier,snapshot in baseline.items():
            row=db.execute('SELECT * FROM papers WHERE id=? AND active=1',(identifier,)).fetchone()
            if not row:missing.append(identifier);continue
            if enrichment_hash(hydrate(row,db))!=enrichment_hash(snapshot['payload']):changed.append(identifier)
            for machine in old.execute('SELECT input_hash,payload FROM enrichments WHERE paper_id=?',(identifier,)):
                current=db.execute('SELECT payload FROM enrichments WHERE paper_id=? AND input_hash=?',(identifier,machine['input_hash'])).fetchone()
                if not current or current[0]!=machine['payload']:translations.append(identifier)
            original_override=old.execute('SELECT payload FROM overrides WHERE paper_id=?',(identifier,)).fetchone()
            if original_override:
                current=db.execute('SELECT payload FROM overrides WHERE paper_id=?',(identifier,)).fetchone()
                if not current or current[0]!=original_override[0]:overrides.append(identifier)
    old.close()
    result={'checked_at':now(),'baseline':len(baseline),'active_ids_missing':missing,
            'translation_inputs_changed':changed,'old_translations_changed':translations,'old_overrides_changed':overrides,
            'passed':not any((missing,changed,translations,overrides))}
    write_json(ROOT/'docs/baseline-preservation.json',result)
    print(json.dumps(result,ensure_ascii=False));assert result['passed']


if __name__=='__main__':main()
