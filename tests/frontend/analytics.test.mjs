import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';

// The user removed operations analytics. Keep that decision protected rather
// than extracting the old runAna closure that no longer exists.
test('dashboard does not restore the removed operations analysis or poll accounts', () => {
  const source = readFileSync(new URL('../../web/frontend/src/components/DashboardPage.tsx', import.meta.url), 'utf8');
  assert.doesNotMatch(source, /OperationsAnalytics|fetchAccountAnalytics|runAna/);
});

test('clipping opens from its own sidebar page without a duplicate library entry', () => {
  const read = name => readFileSync(new URL('../../web/frontend/src/' + name, import.meta.url), 'utf8');
  assert.match(read('components/Sidebar.tsx'), /page: 'clipify', Icon: IconVideo, label: '直播切片'/);
  assert.match(read('App.tsx'), /case 'clipify':[\s\S]*?<ClipifyPanel \/>/);
  assert.doesNotMatch(read('components/OutputsPage.tsx'), /ClipifyPanel|clipifyOpen/);
});
