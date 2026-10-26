"""The API with the test-only stand-in model, for checking the frontend's AI paths in a browser without a real model:
graphics on the stream, Ask OffBall's streamed tools, producer approvals and corrections. It never ships: the
stand-in writes fixed lines, and its Fact-checker re-check after a correction always fails, so corrections show.

    uv run python -m tests.stand_in_server        (port 8010)
"""

from __future__ import annotations

import uvicorn

from offball.agents.crew import Crew
from offball.services import api
from tests.conftest import ScriptedModel


def main() -> None:
    model = ScriptedModel(reject_rechecks=True)
    api._crew = Crew.with_clients({"fast": model, "reasoning": model})
    api.model_configured = lambda: True
    uvicorn.run(api.app, host="127.0.0.1", port=8010, log_level="info")


if __name__ == "__main__":
    main()
