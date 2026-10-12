import argparse
import json
import sys
from .collect import sync
from .enrich import enrich
from .storage import all_papers, export


def main():
    parser = argparse.ArgumentParser(description='TopConf Atlas — all officially accepted papers')
    commands = parser.add_subparsers(dest='command', required=True)
    s = commands.add_parser('sync', help='Fetch official source snapshots and reconcile all accepted papers')
    s.add_argument('--conference')
    s.add_argument('--offline', action='store_true')
    e = commands.add_parser('enrich', help='Translate full abstracts and generate descriptions and labels')
    e.add_argument('--conference')
    e.add_argument('--workers', type=int, default=4)
    e.add_argument('--batch-size', type=int, default=3)
    e.add_argument('--limit', type=int)
    e.add_argument('--repair', action='store_true', help='Reprocess flagged machine translations as well as pending papers')
    commands.add_parser('export', help='Write portable JSON per paper and full catalog')
    commands.add_parser('status')
    commands.add_parser('audit', help='Check source hashes, acceptance evidence and complete Chinese coverage')
    commands.add_parser('recheck', help='Revalidate saved machine translations without calling a model')
    commands.add_parser('serve')
    pdf = commands.add_parser('pdf', help='Cache full-text PDFs, validate bytes and record download provenance')
    pdf.add_argument('--conference')
    pdf.add_argument('--workers', type=int, default=3)
    pdf.add_argument('--limit', type=int)
    pdf.add_argument('--refresh', action='store_true')
    args = parser.parse_args()
    if args.command == 'sync':
        reports = sync(args.conference, args.offline)
        export()
        sys.exit(0 if reports and all(r['status'] == 'success' for r in reports) else 1)
    elif args.command == 'enrich':
        if args.workers < 1 or args.batch_size < 1:
            parser.error('workers and batch-size must be positive')
        report = enrich(args.conference, args.workers, args.batch_size, args.limit, args.repair)
        export()
        sys.exit(1 if report['errors'] else 0)
    elif args.command == 'recheck':
        from .enrich import recheck_quality
        report = recheck_quality()
        export()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        sys.exit(1 if report['errors'] else 0)
    elif args.command == 'export':
        print('Exported', export(), 'papers')
    elif args.command == 'pdf':
        from .pdf import download
        result = download(args.conference, args.workers, args.limit, args.refresh)
        sys.exit(0 if result['cached'] == result['requested'] else 1)
    elif args.command == 'status':
        from .server import status
        print(json.dumps(status(), ensure_ascii=False, indent=2))
    elif args.command == 'audit':
        from .audit import audit
        result = audit()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0 if result['passed'] else 1)
    elif args.command == 'serve':
        import uvicorn
        import os
        uvicorn.run('atlas.server:app', host=os.environ.get('ATLAS_HOST', '127.0.0.1'),
                    port=int(os.environ.get('ATLAS_PORT', '18766')))


if __name__ == '__main__':
    main()
