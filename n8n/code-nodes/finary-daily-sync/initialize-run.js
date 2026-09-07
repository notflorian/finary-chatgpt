const executionId = sourceExecutionId($execution.id);
let nonce;
try { nonce = require('crypto').randomUUID(); } catch { throw new Error('RUN_IDENTITY_UNAVAILABLE'); }
const now = new Date();
const parts = Object.fromEntries(new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Paris', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' }).formatToParts(now).filter((part) => part.type !== 'literal').map((part) => [part.type, part.value]));
const localMillis = Date.UTC(Number(parts.year), Number(parts.month) - 1, Number(parts.day), Number(parts.hour), Number(parts.minute), Number(parts.second));
const offsetMinutes = Math.round((localMillis - now.getTime()) / 60000);
const sign = offsetMinutes >= 0 ? '+' : '-';
const absoluteOffset = Math.abs(offsetMinutes);
const offset = `${sign}${String(Math.floor(absoluteOffset / 60)).padStart(2, '0')}:${String(absoluteOffset % 60).padStart(2, '0')}`;
const localTimestamp = `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:${parts.second}${offset}`;
return [{ json: { run_id: runIdentity(executionId, nonce), started_at: localTimestamp, started_epoch_ms: now.getTime() } }];