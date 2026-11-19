/**
 * The conversation feed on the talk screen: what the visitor said and what the agent answered, in order.
 * The server streams an answer as many assistant_text pieces tagged with the turn's id; pieces of one turn
 * join into one message. An interrupted turn's answer is dropped, as the old page cleared it, because its
 * text runs ahead of the audio the visitor actually heard.
 */

export interface ConvoMessage {
  id: number;
  who: 'agent' | 'user';
  text: string;
  turnId: number | null; // the agent turn this answer belongs to; null for the visitor's words
}

let nextId = 1;

/** The visitor's finished words become a message of their own. */
export function addVisitorWords(feed: ConvoMessage[], text: string): ConvoMessage[] {
  if (!text.trim()) return feed;
  return [...feed, { id: nextId++, who: 'user', text, turnId: null }];
}

/** A piece of the agent's answer: joins the last message when it is the same turn's, else starts a new one. */
export function addAgentText(feed: ConvoMessage[], turnId: number | null, text: string): ConvoMessage[] {
  const last = feed.at(-1);
  if (last && last.who === 'agent' && last.turnId === turnId) {
    return [...feed.slice(0, -1), { ...last, text: last.text + text }];
  }
  return [...feed, { id: nextId++, who: 'agent', text, turnId }];
}

/** Drops the answer of an interrupted turn; earlier answers and the visitor's words stay. */
export function dropTurn(feed: ConvoMessage[], turnId: number): ConvoMessage[] {
  return feed.filter((message) => message.who === 'user' || message.turnId !== turnId);
}

/** Elapsed time as m:ss, for the interview timer. */
export function clock(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`;
}
