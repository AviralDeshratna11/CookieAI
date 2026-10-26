const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function portal(turn) {
  const elements = new Map();
  function element() {
    return { textContent: '', isConnected: true, children: [], addEventListener() {}, append(...items) { this.children.push(...items); } };
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
  return { context, scheduled, reply: context.reply };
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
