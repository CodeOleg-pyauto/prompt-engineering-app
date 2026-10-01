"""МИР • Промпт: portable desktop activity with offline rule-based scoring."""
from __future__ import annotations

import argparse
import logging
import json
from pathlib import Path
import sys
import tempfile

from prompt_rules import TaskPack
from session import ParticipantSession
from result_store import ResultStore
from settings import application_dir, load_settings, results_dir, event_day


def resource_dir() -> Path:
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))


def show_startup_error(message: str) -> None:
    print(message, file=sys.stderr)
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, 'МИР • Промпт — ошибка запуска', 0x10)


def main() -> int:
    parser = argparse.ArgumentParser(description='МИР • Промпт — офлайн-испытание')
    parser.add_argument('--fullscreen', action='store_true')
    parser.add_argument('--check', action='store_true', help='Проверить ресурсы и библиотеки')
    args = parser.parse_args()
    html = resource_dir() / 'ui' / 'index.html'
    resources = [html, html.parent / 'app.js', html.parent / 'app.ico', resource_dir() / 'tasks.json']
    missing = next((p for p in resources if not p.is_file()), None)
    if missing:
        show_startup_error(f'Не найден ресурс: {missing}\nРаспакуйте весь архив в одну папку.')
        return 1

    try:
        from PySide6.QtCore import Qt, QUrl, QObject, Slot, QTimer, Signal
        from PySide6.QtWebChannel import QWebChannel
        from PySide6.QtGui import QIcon, QKeySequence, QShortcut
        from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox
        from PySide6.QtWebEngineCore import (
            QWebEnginePage, QWebEngineProfile, QWebEngineSettings,
            QWebEngineUrlRequestInterceptor,
        )
        from PySide6.QtWebEngineWidgets import QWebEngineView
    except ImportError as exc:
        show_startup_error(
            'Не загружены библиотеки приложения.\n'
            'Запустите START.bat, чтобы подготовить окружение.\n\n' + str(exc)
        )
        return 1
    pack = TaskPack(resource_dir() / 'tasks.json')
    config = load_settings(application_dir())
    store = ResultStore(results_dir(application_dir(), config))
    if args.check:
        print(f'OK: PySide6, Qt WebEngine, Qt WebChannel, HTML, {len(pack.tasks)} tasks')
        return 0

    class Bridge(QObject):
        expired = Signal()

        def __init__(self, parent=None):
            super().__init__(parent)
            self.session = ParticipantSession(pack, store=store, limit_seconds=config['time_limit_seconds'],
                                              multiplier=config['score_multiplier'], day_provider=lambda: event_day(config))
            self.deadline_sent = False
            self.timer = QTimer(self)
            self.timer.setInterval(250)
            self.timer.timeout.connect(self.check_deadline)
            self.timer.start()

        def check_deadline(self):
            status = self.session.status()
            if status['active'] and status['remaining_ms'] == 0 and not self.deadline_sent:
                self.deadline_sent = True
                self.expired.emit()

        def respond(self, action, *values):
            try:
                data = action(*values)
                response = {'ok': True, 'data': data}
            except ValueError as exc:
                response = {'ok': False, 'error': str(exc)}
            except Exception:
                # Do not log names or prompt contents from participant actions.
                response = {'ok': False, 'error': 'Не удалось обработать запрос. Обратись к организатору.'}
            return json.dumps(response, ensure_ascii=False)

        @Slot(str, str, result=str)
        def start(self, first, last):
            self.deadline_sent = False
            return self.respond(self.session.start, first, last)

        @Slot(result=str)
        def status(self):
            return self.respond(self.session.status)

        @Slot(result=str)
        def recover(self):
            return self.respond(store.recover)

        @Slot(result=str)
        def retrySave(self):
            return self.respond(self.session.retry_save)

        @Slot(str, result=str)
        def evaluate(self, prompt):
            return self.respond(self.session.evaluate, prompt)

        @Slot(result=str)
        def finish(self):
            return self.respond(self.session.finish)

    class LocalRequests(QWebEngineUrlRequestInterceptor):
        def interceptRequest(self, info):
            # Allow only packaged resources and Qt's embedded channel script.
            url = info.requestUrl()
            allowed = url.scheme() in ('data', 'about') or (
                url.scheme() == 'qrc' and url.path() == '/qtwebchannel/qwebchannel.js'
            ) or (
                url.isLocalFile() and Path(url.toLocalFile()).resolve() in
                {html.resolve(), (html.parent / 'app.js').resolve()}
            )
            if not allowed:
                info.block(True)

    class LocalPage(QWebEnginePage):
        def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
            return url.scheme() in ('data', 'about') or (url.scheme() == 'qrc' and url.path() == '/mirprompt/')

        def createWindow(self, window_type):
            return None

        def javaScriptConsoleMessage(self, level, message, line_number, source_id):
            # Never log participant names or prompts from the web interface.
            pass

    class MainWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle('МИР • Промпт · Колледж «МИР»')
            self.setWindowIcon(QIcon(str(resource_dir() / 'ui' / 'app.ico')))
            self.resize(1366, 900)
            self.setMinimumSize(800, 600)
            self.view = QWebEngineView(self)
            self.setCentralWidget(self.view)
            # Browser cache stays in memory; result JSONs are written by ResultStore.
            self.profile = QWebEngineProfile(self)
            self.profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
            self.profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
            self.interceptor = LocalRequests(self.profile)
            self.profile.setUrlRequestInterceptor(self.interceptor)
            self.profile.downloadRequested.connect(lambda download: download.cancel())
            self.page = LocalPage(self.profile, self.view)
            self.view.setPage(self.page)
            self.channel = QWebChannel(self.page)
            self.bridge = Bridge(self.channel)
            self.channel.registerObject('activity', self.bridge)
            self.page.setWebChannel(self.channel)
            settings = self.page.settings()
            settings.setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, True)
            settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
            settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, False)
            self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
            self.page.fullScreenRequested.connect(self.on_web_fullscreen)
            self.view.loadFinished.connect(self.on_loaded)
            self.fullscreen_shortcut = QShortcut(QKeySequence('F11'), self)
            self.fullscreen_shortcut.activated.connect(self.toggle_fullscreen)
            # Read packaged files once in Python, then load the page from memory.
            # This avoids Chromium navigation to UNC paths on a network share.
            content = html.read_text(encoding='utf-8').replace(
                '<script src="app.js"></script>',
                '<script>' + (html.parent / 'app.js').read_text(encoding='utf-8') + '</script>')
            self.view.setHtml(content, QUrl('qrc:///mirprompt/'))

        def closeEvent(self, event):
            s = self.bridge.session
            if s.participant is not None and (s.result is None or not s.storage or not s.storage['saved']):
                answer = QMessageBox.question(self, 'Незавершённая попытка',
                    'Попытка не завершена или результат не записан на сетевой диск. Закрыть приложение?',
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
                if answer != QMessageBox.StandardButton.Yes:
                    event.ignore()
                    return
            event.accept()

        def on_loaded(self, ok):
            if not ok:
                QMessageBox.critical(self, 'МИР • Промпт',
                    'Не удалось загрузить интерфейс.\nПроверьте, что папка ui находится рядом с main.py.')

        def on_web_fullscreen(self, request):
            request.accept()
            if request.toggleOn():
                self.showFullScreen()
            else:
                self.showMaximized()

        def toggle_fullscreen(self):
            if self.isFullScreen():
                self.page.runJavaScript(
                    'if (document.fullscreenElement) document.exitFullscreen();'
                )
                self.showMaximized()
            else:
                self.showFullScreen()

    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('CollegeMIR.MirPrompt.1')
    app = QApplication(sys.argv[:1])
    app.setApplicationName('МИР • Промпт')
    app.setWindowIcon(QIcon(str(resource_dir() / 'ui' / 'app.ico')))
    app.setOrganizationName('Колледж МИР')
    window = MainWindow()
    if args.fullscreen:
        window.showFullScreen()
    else:
        window.showMaximized()
    return app.exec()


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        # Startup tracebacks contain only launcher information, not form contents.
        log_path = Path(tempfile.gettempdir()) / 'MirPrompt-startup-error.log'
        logging.basicConfig(filename=log_path, level=logging.ERROR, encoding='utf-8')
        logging.exception('Application startup failed')
        show_startup_error(f'Не удалось запустить приложение.\nПодробности: {log_path}')
        raise SystemExit(1)
