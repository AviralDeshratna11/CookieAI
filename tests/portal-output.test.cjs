const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function portal(turn) {
  const elements = new Map();
  function element() {
    return { textContent: '', isConnected: true, children: [], attributes: {}, hidden: false, addEventListener() {}, focus() {}, setAttribute(key,value) {this.attributes[key] = value;}, removeAttribute(key) {delete this.attributes[key];}, replaceChildren(...items) {this.children = items;}, append(...items) { this.children.push(...items); } };
  }
  const scheduled = [];
  const context = vm.createContext({
    crypto: { randomUUID: () => 'session' },
    sessionStorage: { getItem() {}, setItem() {} },
    document: {
      getElementById(id) { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); },
      querySelectorAll: () => [], createElement: element,
    },
    fetch: async () => { if (turn instanceof Error) throw turn; return { ok: true, status: 200, json: async () => turn }; },
    setTimeout: callback => scheduled.push(callback), clearTimeout() {},
  });
  vm.runInContext(fs.readFileSync('apps/api/static/portal.js', 'utf8'), context);
  vm.runInContext("token = 'test-token'", context);
  context.reply = element();
  return { context, scheduled, reply: context.reply, elements };
}

test('shows the API top-level answer rather than a JSON status', async () => {
  const p = portal({ status: 'COMPLETED', answer: 'First line\nSecond line', memory_ids: ['private-metadata'] });
  await vm.runInContext("pollTurn('turn-id', reply)", p.context);
  assert.equal(p.reply.textContent, 'First line\nSecond line');
  assert.equal(p.scheduled.length, 0);
});

test('shows an available answer while memory processing continues', async () => {
  const p = portal({ status: 'RESPONDED', answer: 'Your answer', job_status: 'RUNNING' });
  await vm.runInContext("pollTurn('turn-id', reply)", p.context);
  assert.equal(p.reply.textContent, 'Your answer');
  assert.equal(p.scheduled.length, 1);
});

test('stops polling an exhausted worker job and keeps any generated answer', async () => {
  const p = portal({ status: 'RESPONDED', answer: 'Saved response', job_status: 'FAILED' });
  await vm.runInContext("pollTurn('turn-id', reply)", p.context);
  assert.match(p.reply.textContent, /^Saved response/);
  assert.match(p.reply.textContent, /could not complete/);
  assert.equal(p.scheduled.length, 0);
});

test('offers a refresh of the same request after a polling error or timeout', async () => {
  for (const turn of [new Error('Network unavailable'), { status: 'PENDING', job_status: 'PENDING' }]) {
    const p = portal(turn);
    await vm.runInContext("pollTurn('turn-id', reply, 120)", p.context);
    assert.match(p.reply.textContent, /Check reply/);
    assert.equal(p.reply.children.at(-1).textContent, 'Check reply');
    assert.equal(p.scheduled.length, 0);
  }
});

test('does not poll replies removed by disconnect', async () => {
  const p = portal({ status: 'COMPLETED', answer: 'Old response' });
  p.reply.isConnected = false;
  await vm.runInContext("pollTurn('turn-id', reply)", p.context);
  assert.equal(p.reply.textContent, '');
  assert.equal(p.scheduled.length, 0);
});

test('debug starts closed and opening correlation never opens the inspector', async () => {
  const p = portal({note: 'fixture', sessions: []});
  assert.equal(vm.runInContext('debugOpen', p.context), false);
  await vm.runInContext("runCorrelation('fixture')", p.context);
  assert.equal(vm.runInContext('debugOpen', p.context), false);
});

test('debug renders untrusted evidence as text rather than executable HTML', () => {
  const p = portal({});
  vm.runInContext("renderDebugValue({text: '<img src=x onerror=alert(1)>'})", p.context);
  const content = p.elements.get('debug-content');
  assert.match(content.children[0].textContent, /<img src=x/);
  assert.equal(content.children[0].innerHTML, undefined);
});

test('debug closes back to chat without retaining its tools in the normal view', () => {
  const p = portal({});
  vm.runInContext('debugOpen = true; setDebugOpen(false)', p.context);
  assert.equal(p.elements.get('debug-panel').hidden, true);
  assert.equal(p.elements.get('tools-nav').hidden, true);
  assert.equal(p.elements.get('debug-toggle').attributes['aria-expanded'], 'false');
});

test('an old completed reply does not replace a newer active trace or release its submit guard', async () => {
  const p = portal({status:'COMPLETED', answer:'Old answer'});
  vm.runInContext("activeTurnId = 'new-turn'; latestTurn = {turn_id:'new-turn'}; chatBusy = true", p.context);
  await vm.runInContext("pollTurn('old-turn', reply)", p.context);
  assert.equal(vm.runInContext('latestTurn.turn_id', p.context), 'new-turn');
  assert.equal(vm.runInContext('chatBusy', p.context), true);
});
