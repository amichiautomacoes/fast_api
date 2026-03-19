from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


TEMPLATE = """from __future__ import annotations

import uvicorn
from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(
        title="Fast API Novo",
        version="1.0.0",
        description="Arquivo gerado automaticamente por create_fast_api.py",
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()


def main() -> None:
    uvicorn.run("fast_api_novo:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Cria um novo arquivo fast_api para o projeto, sem sobrescrever por padrao."
    )
    parser.add_argument(
        "--output",
        default="fast_api_novo.py",
        help="Caminho de saida do novo arquivo fast_api (padrao: fast_api_novo.py).",
    )
    parser.add_argument(
        "--mode",
        choices=("clone", "template"),
        default="clone",
        help="Modo clone copia o fast_api atual; template gera um fast_api basico.",
    )
    parser.add_argument(
        "--source",
        default="../01api_webhook/fast_api.py",
        help="Arquivo fonte usado no modo clone (padrao: 01api_webhook/fast_api.py).",
    )
    parser.add_argument("--force", action="store_true", help="Permite sobrescrever o arquivo de saida.")
    parser.add_argument("--dry-run", action="store_true", help="Mostra o que seria feito sem criar arquivo.")
    return parser.parse_args()


def resolve_path(value: str, project_root: Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = project_root / path
    return path.resolve()


def main() -> int:
    args = parse_args()
    project_root = Path(__file__).resolve().parent
    source = resolve_path(args.source, project_root)
    output = resolve_path(args.output, project_root)

    if args.mode == "clone" and not source.exists():
        print(f"Erro: arquivo fonte nao encontrado: {source}")
        return 1

    if output.exists() and not args.force:
        print(f"Erro: arquivo de saida ja existe: {output}")
        print("Use --force para sobrescrever ou --output para outro nome.")
        return 1

    if args.dry_run:
        print(f"[dry-run] mode={args.mode}")
        if args.mode == "clone":
            print(f"[dry-run] source={source}")
        print(f"[dry-run] output={output}")
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)

    if args.mode == "clone":
        shutil.copy2(source, output)
    else:
        output.write_text(TEMPLATE, encoding="utf-8")

    print(f"Arquivo criado: {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
