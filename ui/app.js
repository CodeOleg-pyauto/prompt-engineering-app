'use strict';
const $ = id => document.getElementById(id);
let activity = null, locked = false, busy = false;
let timer = null, statusBusy = false, expired = false, storageSaved = false;

function stopTimer() { if (timer !== null) clearInterval(timer); timer = null; }
function openDialog(id) {
  $(id).hidden = false;
  if (id === 'confirm') { stopTimer(); $('cancel').focus(); }
  else $('closeHelp').focus();
}
function closeDialog(id) {
  $(id).hidden = true;
  if (id === 'confirm' && !busy && locked && !$('task').hidden) {
    $('prompt').focus();
    call('status').then(s => {
      if (!s.active || busy || $('task').hidden) return;
      if (s.remaining_ms === 0) deadline();
      else startTimer(s.remaining_ms);
    }).catch(e => error('taskError', e.message));
  }
}
document.addEventListener('keydown', e => {
  const id = !$('confirm').hidden ? 'confirm' : !$('helpDialog').hidden ? 'helpDialog' : null;
  if (!id) return;
  if (e.key === 'Escape') { e.preventDefault(); closeDialog(id); return; }
  if (e.key === 'Tab') {
    const buttons = $(id).querySelectorAll('button:not(:disabled)');
    const first = buttons[0], last = buttons[buttons.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }
});
function showTime(ms) {
  const seconds = Math.ceil(ms / 1000);
  $('timeLeft').textContent = String(Math.floor(seconds / 60)).padStart(2, '0') + ':' + String(seconds % 60).padStart(2, '0');
  $('timeLeft').classList.toggle('urgent', seconds <= 60);
}
function startTimer(ms) {
  stopTimer(); expired = false; showTime(ms);
  timer = setInterval(async () => {
    if (statusBusy || busy) return;
    statusBusy = true;
    try {
      const s = await call('status'); showTime(s.remaining_ms);
      if (s.active && s.remaining_ms === 0) deadline();
    } catch (e) { error('taskError', 'Не удалось обновить таймер. Обратись к организатору.'); }
    finally { statusBusy = false; }
  }, 500);
}
function deadline() {
  expired = true; showTime(0);
  if (locked && !busy && !$('task').hidden) sendPrompt();
}
function storageView(s) {
  storageSaved = Boolean(s.saved);
  $('saveStatus').textContent = s.message;
  $('saveStatus').className = storageSaved ? 'saved' : 'error';
  $('retrySave').hidden = storageSaved;
  $('finish').disabled = !storageSaved;
}

function screen(id, step) {
  ['welcome', 'task', 'loading', 'result'].forEach(x => $(x).hidden = x !== id);
  document.querySelectorAll('.step').forEach((e, i) => {
    e.classList.toggle('active', i === step);
    e.classList.toggle('done', i < step);
    if (i === step) e.setAttribute('aria-current', 'step');
    else e.removeAttribute('aria-current');
  });
  window.scrollTo(0, 0);
}

function nameValue(value) {
  const v = value.trim();
  if (!v || v.length > 50 || !/^[А-Яа-яЁё]+(?:[- ][А-Яа-яЁё]+)*$/.test(v)) return null;
  return v.toLocaleLowerCase('ru').replace(/(^|[- ])[а-яё]/g, x => x.toLocaleUpperCase('ru'));
}

function error(id, message) { $(id).textContent = message; $(id).hidden = !message; }

function call(method, ...args) {
  return new Promise((resolve, reject) => {
    if (!activity) { reject(new Error('Открой приложение через START.bat или MirPrompt.exe.')); return; }
    activity[method](...args, raw => {
      try {
        const r = JSON.parse(raw);
        if (!r.ok) throw new Error(r.error || 'Не удалось обработать запрос.');
        resolve(r.data);
      } catch (e) { reject(e); }
    });
  });
}

function taskView(task) {
  $('taskTitle').textContent = task.title;
  $('taskBadge').textContent = 'ЗАДАНИЕ ' + task.id.replace('task_', '');
  $('taskDescription').textContent = task.statement.split('\n\n')[0];
  const list = $('taskRequirements'); list.replaceChildren();
  task.requirements.forEach((text, i) => {
    const li = document.createElement('li'), n = document.createElement('b'), content = document.createElement('span');
    n.textContent = i + 1; content.textContent = text; li.append(n, content); list.append(li);
  });
}

function resultView(r) {
  $('score').textContent = r.score;
  const angle = r.score / r.max_score * 360;
  $('maxScore').textContent = 'из ' + r.max_score + ' баллов';
  $('scoreRing').style.background = r.score === 0 ? '#e3e7f4' :
    `conic-gradient(#0045ff 0deg, #ac28f2 ${angle}deg, #e3e7f4 ${angle}deg)`;
  $('resultTask').textContent = r.task_title;
  const requirements = r.requirements_score ?? r.score, requirementsMax = r.requirements_max_score ?? r.max_score;
  $('scoreHeading').textContent = requirements === requirementsMax ? 'Все требования учтены!' : requirements >= requirementsMax * .7 ? 'Хорошее начало!' : 'Есть куда расти!';
  $('scoreFormula').textContent = r.minute_bonus === undefined ? '' : `${requirements} за требования + ${r.minute_bonus} за оставшиеся полные минуты = ${r.score}`;
  const seconds = Math.floor(r.duration_ms / 1000);
  $('attemptTime').textContent = 'Время: ' + Math.floor(seconds / 60) + ' мин ' + seconds % 60 + ' сек' + (r.auto_submitted ? ' · отправлено по таймеру' : '');
  storageView(r.storage);
  $('resultNotice').textContent = r.notice;
  $('reviewNotice').hidden = !r.requires_review;
  const list = $('criteria'); list.replaceChildren();
  r.criteria.forEach(c => {
    const row = document.createElement('div'), header = document.createElement('div');
    header.className = 'criterionheader';
    const label = document.createElement('span'), points = document.createElement('b');
    label.textContent = c.title; points.textContent = `${c.points} / ${c.max_points}`;
    header.append(label, points);
    const track = document.createElement('div'), fill = document.createElement('i');
    track.className = 'track'; fill.style.width = (100 * c.points / c.max_points) + '%'; track.append(fill);
    const details = document.createElement('details'), summary = document.createElement('summary'), text = document.createElement('p');
    summary.textContent = 'Почему такой балл'; text.textContent = c.explanation; details.append(summary, text);
    c.evidence.forEach(e => { const quote = document.createElement('blockquote'); quote.textContent = e.text; details.append(quote); });
    row.append(header, track, details); list.append(row);
  });
  const feedback = $('recommendations'); feedback.replaceChildren();
  const items = r.recommendations.length ? r.recommendations : ['Обязательные требования распознаны. Ты можешь дополнительно продумать обработку ошибок и удобство интерфейса.'];
  items.forEach(text => { const li = document.createElement('li'); li.textContent = text; feedback.append(li); });
}

for (const id of ['first', 'last']) {
  $(id).addEventListener('blur', () => { const v = nameValue($(id).value); if (v) $(id).value = v; });
  $(id).addEventListener('input', () => { $(id).removeAttribute('aria-invalid'); error('nameerror', ''); });
}

$('registration').addEventListener('submit', async e => {
  e.preventDefault(); if (locked || busy) return;
  const first = nameValue($('first').value), last = nameValue($('last').value);
  if (!first || !last) {
    for (const [id, value] of [['first', first], ['last', last]]) $(id).setAttribute('aria-invalid', String(!value));
    error('nameerror', 'Введи имя и фамилию русскими буквами. Можно использовать пробел или дефис между частями. Латиница и цифры не подходят.');
    $(!first ? 'first' : 'last').focus(); return;
  }
  busy = true; $('start').disabled = true; error('nameerror', '');
  try {
    const r = await call('start', first, last);
    locked = true;
    for (const id of ['first', 'last']) { $(id).value = r.participant[id]; $(id).disabled = true; }
    document.querySelectorAll('.person').forEach(e => e.textContent = r.participant.first + ' ' + r.participant.last);
    document.querySelectorAll('.initials').forEach(e => e.textContent = (r.participant.first[0] + r.participant.last[0]).toLocaleUpperCase('ru'));
    taskView(r.task); screen('task', 1); startTimer(r.remaining_ms); $('prompt').focus();
  } catch (e) { error('nameerror', e.message); }
  finally { busy = false; $('start').disabled = !activity; if (expired) deadline(); }
});

$('prompt').addEventListener('input', () => {
  $('count').textContent = $('prompt').value.length.toLocaleString('ru') + ' / 6 000 символов';
  $('submit').disabled = !$('prompt').value.trim() || busy;
  error('taskError', '');
});
$('submit').addEventListener('click', () => { if (!busy && $('prompt').value.trim()) openDialog('confirm'); });
$('cancel').onclick = () => closeDialog('confirm');
$('confirmSend').onclick = () => sendPrompt();
async function sendPrompt() {
  if (busy) return;
  busy = true; stopTimer(); closeDialog('confirm'); closeDialog('helpDialog'); $('prompt').readOnly = true; $('submit').disabled = true;
  error('taskError', ''); screen('loading', 1);
  try {
    const r = await call('evaluate', $('prompt').value);
    stopTimer(); resultView(r); screen('result', 2); $('finish').focus();
  } catch (e) {
    $('prompt').readOnly = expired; $('submit').disabled = !expired && !$('prompt').value.trim();
    error('taskError', e.message); screen('task', 1);
    if (!expired) call('status').then(s => { if (s.active && !busy) startTimer(s.remaining_ms); }).catch(e => error('taskError', e.message));
  } finally { busy = false; }
}

$('retrySave').onclick = async () => {
  if (busy) return;
  busy = true; $('retrySave').disabled = true;
  try { storageView(await call('retrySave')); error('resultError', ''); }
  catch (e) { error('resultError', e.message); }
  finally { busy = false; $('retrySave').disabled = false; }
};

$('finish').onclick = async () => {
  if (busy || !storageSaved) return;
  busy = true; $('finish').disabled = true;
  try {
    await call('finish'); locked = false; stopTimer(); expired = false; storageSaved = false;
    $('registration').reset();
    for (const id of ['first', 'last']) { $(id).disabled = false; $(id).removeAttribute('aria-invalid'); }
    error('nameerror', ''); error('taskError', ''); error('resultError', '');
    $('prompt').value = ''; $('prompt').readOnly = false; $('submit').disabled = true;
    $('count').textContent = '0 / 6 000 символов';
    document.querySelectorAll('.person,.initials').forEach(e => e.textContent = '');
    $('criteria').replaceChildren(); $('recommendations').replaceChildren();
    $('taskRequirements').replaceChildren(); $('taskTitle').textContent = $('taskDescription').textContent = $('taskBadge').textContent = '';
    $('resultTask').textContent = $('resultNotice').textContent = ''; $('score').textContent = '0';
    $('scoreRing').style.background = '#e3e7f4'; $('reviewNotice').hidden = true;
    $('saveStatus').textContent = $('attemptTime').textContent = $('scoreFormula').textContent = ''; $('retrySave').hidden = true;
    screen('welcome', 0); $('first').focus();
  } catch (e) { error('resultError', e.message); }
  finally { busy = false; $('finish').disabled = !storageSaved; }
};
$('help').onclick = () => openDialog('helpDialog');
$('closeHelp').onclick = () => closeDialog('helpDialog');
$('fullscreen').onclick = async () => {
  try { if (!document.fullscreenElement) await document.documentElement.requestFullscreen(); else await document.exitFullscreen(); }
  catch (e) { openDialog('helpDialog'); }
};

if (typeof QWebChannel === 'function' && typeof qt !== 'undefined' && qt.webChannelTransport) {
  new QWebChannel(qt.webChannelTransport, channel => {
    activity = channel.objects.activity;
    if (activity) {
      activity.expired.connect(deadline);
      call('recover').then(r => {
        if (r.pending) error('nameerror', 'Есть локальные результаты, которые пока не удалось восстановить. Сообщи организатору.');
      }).catch(e => error('nameerror', e.message)).finally(() => $('start').disabled = false);
    }
    if (!activity) error('nameerror', 'Не загружен модуль проверки. Перезапусти приложение.');
  });
} else error('nameerror', 'Для проверки заданий открой START.bat или MirPrompt.exe. Отдельный HTML показывает только интерфейс.');
