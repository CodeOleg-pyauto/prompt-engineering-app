// DOM/bridge contract tests; this is not a Windows or Chromium visual test.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const fixtures = JSON.parse(execFileSync(process.platform === 'win32' ? 'python' : 'python3', ['-c',
  'from prompt_rules import TaskPack; import json; p=TaskPack(); t=p.tasks["task_01"]; print(json.dumps({"task":p.public_task("task_01"),"good":p.evaluate("task_01",t["example_full_prompt"]),"zero":p.evaluate("task_01","Привет")}))'], {cwd:root, encoding:'utf8'}));
class Element {
  constructor() { this.value = ''; this.textContent = ''; this.children = []; this.style = {}; this.attrs = {}; this.handlers = {}; this.hidden = false; this.disabled = false; this.classList = {toggle(){}}; }
  addEventListener(name, cb) { this.handlers[name] = cb; }
  setAttribute(k,v) { this.attrs[k] = v; }
  removeAttribute(k) { delete this.attrs[k]; }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = items; }
  showModal() { this.open = true; }
  close() { this.open = false; }
  focus() {}
}
const html = fs.readFileSync(path.join(root,'ui/index.html'),'utf8');
const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map(m=>m[1]);
assert.equal(new Set(ids).size, ids.length, 'HTML IDs must be unique');
const elements = Object.fromEntries(ids.map(id=>[id,new Element()]));
elements.confirm.hidden=elements.helpDialog.hidden=true;
elements.registration.reset = () => { elements.first.value = elements.last.value = ''; };
const people = [new Element(),new Element()], initials = [new Element(),new Element()], steps = [new Element(),new Element(),new Element()];
let starts=0, evaluations=0, finishes=0, failEvaluation=false;
let failStorage=false, expiryHandler=null;
for (const r of [fixtures.good, fixtures.zero]) {
  r.duration_ms=1500; r.auto_submitted=false;
  r.storage={saved:true,message:'Сохранено'};
}
fixtures.good.requirements_score=100;fixtures.good.requirements_max_score=100;
fixtures.good.minute_bonus=5;fixtures.good.score=105;fixtures.good.max_score=110;fixtures.good.duration_ms=300000;
const bridge = {
  expired:{connect(cb){expiryHandler=cb;}},
  recover(cb){setImmediate(()=>cb(JSON.stringify({ok:true,data:{pending:0,recovered:0}})));},
  status(cb){cb(JSON.stringify({ok:true,data:{active:true,remaining_ms:5000}}));},
  retrySave(cb){cb(JSON.stringify({ok:true,data:{saved:true,message:'Сохранено'}}));},
  start(first,last,cb) { starts++; setImmediate(()=>cb(JSON.stringify({ok:true,data:{participant:{first,last},task:fixtures.task,remaining_ms:600000}}))); },
  evaluate(prompt,cb) { evaluations++; const r=structuredClone(prompt==='Привет'||prompt===''?fixtures.zero:fixtures.good); r.storage={saved:!failStorage,message:'Статус записи'};r.auto_submitted=prompt==='';setImmediate(()=>cb(JSON.stringify(failEvaluation ? {ok:false,error:'Ошибка проверки'} : {ok:true,data:r}))); },
  finish(cb) { finishes++; setImmediate(()=>cb(JSON.stringify({ok:true,data:{}}))); }
};
const ctx = vm.createContext({
  document:{addEventListener(){},getElementById(id){assert.ok(elements[id],`Missing HTML ID: ${id}`);return elements[id];}, createElement(){return new Element();},
    querySelectorAll(s){return s==='.step'?steps:s==='.person'?people:s==='.initials'?initials:[...people,...initials];}},
  window:{scrollTo(){}}, qt:{webChannelTransport:{}},
  QWebChannel:function(transport,cb){cb({objects:{activity:bridge}});},
  console, Promise
  ,setInterval(){return 1;},clearInterval(){}
});
vm.runInContext(fs.readFileSync(path.join(root,'ui/app.js'),'utf8'),ctx);
const submit=()=>elements.registration.handlers.submit({preventDefault(){}});
const input=text=>{elements.prompt.value=text;elements.prompt.handlers.input();};
const visible=id=>assert.equal(elements[id].hidden,false);
(async()=>{
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(elements.start.disabled,false);
  elements.first.value='Ивaн'; elements.last.value='Иванов'; await submit();
  assert.equal(starts,0); assert.equal(elements.nameerror.hidden,false);
  elements.first.value='иВАН'; elements.last.value='ИВАНОВ';
  const pending=submit(); await submit(); await pending;
  assert.equal(starts,1); visible('task'); assert.equal(people[0].textContent,'Иван Иванов');
  assert.equal(elements.taskRequirements.children.length,7); assert.equal(elements.first.disabled,true);
  input('Привет'); elements.submit.handlers.click(); assert.equal(elements.confirm.hidden,false);
  await elements.confirmSend.onclick(); visible('result'); assert.equal(elements.score.textContent,0);
  assert.equal(elements.criteria.children.length,7); assert.ok(elements.recommendations.children.length);
  await elements.finish.onclick(); visible('welcome'); assert.equal(finishes,1);
  assert.equal(people[0].textContent,''); assert.equal(elements.prompt.value,''); assert.equal(elements.criteria.children.length,0);
  elements.first.value='анна-мАРИЯ'; elements.last.value='ЁЛКИНА'; await submit();
  assert.equal(people[0].textContent,'Анна-Мария Ёлкина');
  input('Полный промпт'); failEvaluation=true; await elements.confirmSend.onclick();
  visible('task'); assert.equal(elements.prompt.readOnly,false); assert.equal(starts,2);
  failEvaluation=false; failStorage=true;
  const sending=elements.confirmSend.onclick(); await elements.confirmSend.onclick(); await sending;
  visible('result'); assert.equal(evaluations,3); assert.equal(elements.score.textContent,105);
  assert.ok(elements.scoreFormula.textContent.includes('100 за требования + 5'));
  assert.equal(elements.criteria.children.length,7);
  assert.equal(elements.finish.disabled,true);
  await elements.finish.onclick(); assert.equal(finishes,1);
  await elements.retrySave.onclick(); assert.equal(elements.finish.disabled,false);
  await elements.finish.onclick(); assert.equal(finishes,2);
  failStorage=false;
  elements.first.value='Иван'; elements.last.value='Иванов';await submit(); input('');
  expiryHandler();await new Promise(resolve=>setImmediate(resolve));await new Promise(resolve=>setImmediate(resolve));
  visible('result');assert.equal(elements.score.textContent,0);assert.ok(elements.attemptTime.textContent.includes('таймеру'));
  await elements.finish.onclick();assert.equal(finishes,3);
  // The app must display participant and prompt evidence as text, never HTML.
  assert.ok(!fs.readFileSync(path.join(root,'ui/app.js'),'utf8').includes('innerHTML'));
  console.log('PASS: registration, scores, repeated clicks, retry, network-save gate, empty timeout, reset, HTML contract');
})().catch(e=>{console.error(e);process.exitCode=1;});
