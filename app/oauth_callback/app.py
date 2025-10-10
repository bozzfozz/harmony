from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, status
from fastapi.responses import HTMLResponse

from app.dependencies import get_oauth_service
from app.oauth.transactions import TransactionNotFoundError, TransactionUsedError
from app.services.oauth_service import OAuthErrorCode, OAuthService

__all__ = ["app_oauth_callback", "create_callback_app"]


def _render_help_page(context: dict[str, Any]) -> str:
    redirect_uri = context.get("redirect_uri") or "http://127.0.0.1:8888/callback"
    host_hint = context.get("public_host_hint")
    manual_url = context.get("manual_url")
    instructions: list[str] = []
    if host_hint:
        instructions.append(
            """
<li>Ersetze <code>127.0.0.1</code> in der Adresszeile durch
<code>{host_hint}</code> und lade die Seite neu.</li>
""".strip().format(host_hint=host_hint)
        )
    else:
        instructions.append(
            """
<li>Ersetze <code>127.0.0.1</code> in der Adresszeile durch die öffentliche IP deines Harmony-Servers
und lade die Seite neu.</li>
""".strip()
        )
    if manual_url:
        instructions.append(
            """
<li>Kopiere die vollständige URL aus der Adresszeile und füge sie unter <code>{manual_url}</code> in Harmony ein.</li>
""".strip().format(manual_url=manual_url)
        )
    instructions_html = "\n".join(instructions)
    host_hint_text = host_hint or "&lt;SERVER_IP&gt;"
    example_url = redirect_uri.replace("127.0.0.1", host_hint_text)
    return f"""
<!DOCTYPE html>
<html lang=\"de\">
<head>
  <meta charset=\"utf-8\" />
  <title>Harmony Spotify OAuth Callback</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem; line-height: 1.5; }}
    code {{ background: #f4f4f4; padding: 0.1rem 0.3rem; border-radius: 3px; }}
    .container {{ max-width: 640px; margin: auto; }}
    .hint {{ background: #fffbe6; border: 1px solid #f0d36b; padding: 1rem; border-radius: 6px; }}
  </style>
</head>
<body>
  <div class=\"container\">
    <h1>Spotify-Anmeldung fast abgeschlossen</h1>
    <p>Harmony hat keinen Autorisierungscode erhalten. Bitte gehe wie folgt vor:</p>
    <ol>
      {instructions_html}
    </ol>
    <div class=\"hint\">
      <strong>Beispiel:</strong><br />
      <code>{redirect_uri}</code><br />
      wird zu<br />
      <code>{example_url}</code>
    </div>
    <p>Der Autorisierungscode ist nur wenige Minuten gültig. Wenn der Aufruf erneut scheitert, starte den Vorgang in Harmony neu.</p>
  </div>
</body>
</html>
"""


def create_callback_app() -> FastAPI:
    app = FastAPI(
        title="Harmony OAuth Callback",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/callback", include_in_schema=False)
    async def oauth_callback(
        state: str | None = None,
        code: str | None = None,
        service: OAuthService = Depends(get_oauth_service),
    ) -> HTMLResponse:
        if not state or not code:
            html = _render_help_page(service.help_page_context())
            return HTMLResponse(content=html, status_code=status.HTTP_200_OK)
        try:
            await service.complete(state=state, code=code)
        except (TransactionNotFoundError, TransactionUsedError):
            message = "Der übergebene State ist unbekannt oder wurde bereits verwendet."
            return HTMLResponse(content=f"<p>{message}</p>", status_code=status.HTTP_400_BAD_REQUEST)
        except ValueError as exc:
            if exc.args and exc.args[0] == OAuthErrorCode.OAUTH_CODE_EXPIRED.value:
                message = "Der Autorisierungscode ist abgelaufen. Bitte starte den Vorgang neu."
                return HTMLResponse(content=f"<p>{message}</p>", status_code=status.HTTP_400_BAD_REQUEST)
            return HTMLResponse(
                content="<p>Die Token-Ausstellung ist fehlgeschlagen.</p>",
                status_code=status.HTTP_502_BAD_GATEWAY,
            )
        script = """
    <script>
      try {
        if (window.opener) {
          window.opener.postMessage({ source: 'harmony.spotify.oauth', result: 'success' }, '*');
        }
      } catch (err) {
        console.warn('postMessage failed', err);
      }
    </script>
    """
        body = f"""
    <!DOCTYPE html>
    <html lang=\"de\">
      <head>
        <meta charset=\"utf-8\" />
        <title>Harmony Spotify OAuth</title>
        <style>
          body {{ font-family: system-ui, sans-serif; text-align: center; padding: 4rem; }}
        </style>
      </head>
      <body>
        <h1>Erfolg!</h1>
        <p>Du kannst dieses Fenster schließen und zu Harmony zurückkehren.</p>
        {script}
      </body>
    </html>
    """
        return HTMLResponse(content=body, status_code=status.HTTP_200_OK)

    return app


app_oauth_callback = create_callback_app()

