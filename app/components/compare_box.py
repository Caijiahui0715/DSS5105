"""The compare box on Favorites: listings are dragged between the favorites and the box (up to
three), and the box's order is the order of the comparison table's columns. Nothing is compared
until Compare is pressed. Made with Streamlit's own component API, without another package."""
import streamlit as st
from streamlit.components.v2 import component
from content.i18n import t
from state.session_store import current, favorite_ids, busy

MAX_COMPARED = 3

# Drawn again only when its data changes. A drag moves the listing on the page at once and sends the
# box's new order; the page then sends the box as it is kept, with a new "rev", so a move that was
# not kept is undone. With a mouse a listing is dragged from anywhere on it, on a touch screen by its
# handle (the rest of it scrolls the page); Enter or Space moves the focused listing to the other side.
_JS = r"""
export default function ({ data, parentElement, setTriggerValue }) {
  const root = parentElement;
  const text = JSON.stringify(data);
  if (root.__drawn === text) return;
  root.__drawn = text;
  let board = root.querySelector('.board');
  if (!board) {
    board = document.createElement('div');
    board.className = 'board';
    root.appendChild(board);
  }
  const make = (tag, className, content) => {
    const node = document.createElement(tag);
    node.className = className;
    if (content !== undefined) node.textContent = content;
    return node;
  };
  board.replaceChildren();
  board.classList.toggle('disabled', !!data.disabled);
  const note = make('p', 'note');
  note.setAttribute('aria-live', 'polite');
  if (data.disabled) note.textContent = data.disabledNote;
  const lists = {};
  for (const spec of data.lists) {
    const column = make('section', 'column ' + spec.id);
    const head = make('div', 'head');
    head.append(make('span', 'name', spec.title));
    if (spec.id === 'in') head.append(make('span', 'count', `${spec.items.length}/${data.max}`));
    const list = make(spec.id === 'in' ? 'ol' : 'ul', 'list');
    list.dataset.list = spec.id;
    list.dataset.empty = spec.empty;
    list.setAttribute('aria-label', spec.title);
    for (const listing of spec.items) {
      const item = make('li', 'item');
      item.dataset.id = listing.id;
      item.tabIndex = data.disabled ? -1 : 0;
      item.title = listing.title;
      item.setAttribute('aria-label', `${listing.title}, ${listing.meta}. ${spec.id === 'in' ? data.keyOut : data.keyIn}`);
      const words = make('span', 'words');
      words.append(make('span', 'title', listing.title), make('span', 'meta', listing.meta));
      item.append(make('span', 'grip', '⠿'), words);
      list.append(item);
    }
    column.append(head, list);
    lists[spec.id] = list;
    board.append(column);
  }
  board.append(note);
  if (root.__focus) {
    board.querySelector(`.item[data-id="${CSS.escape(root.__focus)}"]`)?.focus();
    root.__focus = null;
  }
  const boxIds = () => [...lists.in.querySelectorAll('.item')].map((item) => item.dataset.id);
  const before = boxIds();
  let noteTimer;
  const tell = (message) => {
    note.textContent = message;
    clearTimeout(noteTimer);
    noteTimer = setTimeout(() => { note.textContent = ''; }, 3000);
  };
  const send = (ids) => {
    if (ids.join('|') !== before.join('|')) setTriggerValue('moved', ids);
  };

  board.onkeydown = (event) => {
    const item = event.target.closest('.item');
    if (!item || data.disabled || (event.key !== 'Enter' && event.key !== ' ')) return;
    event.preventDefault();
    const id = item.dataset.id;
    const inBox = item.parentElement === lists.in;
    if (!inBox && before.length >= data.max) return tell(data.full);
    root.__focus = id;
    send(inBox ? before.filter((other) => other !== id) : [...before, id]);
  };

  board.onpointerdown = (event) => {
    const item = event.target.closest('.item');
    if (!item || data.disabled || event.button !== 0) return;
    if (event.pointerType !== 'mouse' && !event.target.closest('.grip')) return;
    event.preventDefault();
    const from = item.parentElement;
    const next = item.nextElementSibling;
    const start = item.getBoundingClientRect();
    const ghost = item.cloneNode(true);
    ghost.classList.add('ghost');
    Object.assign(ghost.style, { left: `${start.left}px`, top: `${start.top}px`, width: `${start.width}px` });
    board.append(ghost);
    // Over the listing, also when a container of the page shifts what "fixed" is measured from.
    const placed = ghost.getBoundingClientRect();
    Object.assign(ghost.style, { left: `${2 * start.left - placed.left}px`, top: `${2 * start.top - placed.top}px` });
    item.classList.add('placeholder');
    board.classList.add('dragging');
    const columns = Object.values(lists).map((list) => list.parentElement);
    const inside = (box, x, y) => x >= box.left && x <= box.right && y >= box.top && y <= box.bottom;

    const move = (moving) => {
      ghost.style.transform = `translate(${moving.clientX - event.clientX}px, ${moving.clientY - event.clientY}px)`;
      columns.forEach((column) => column.classList.remove('over', 'full'));
      const column = columns.find((each) => inside(each.getBoundingClientRect(), moving.clientX, moving.clientY));
      if (!column) return;
      const list = column.querySelector('.list');
      const others = [...list.querySelectorAll('.item')].filter((other) => other !== item);
      if (list === lists.in && item.parentElement !== lists.in && others.length >= data.max) {
        column.classList.add('full');
        tell(data.full);
        return;
      }
      column.classList.add('over');
      const after = others.find((other) => {
        const box = other.getBoundingClientRect();
        return moving.clientY < box.top + box.height / 2;
      });
      if (after !== item.nextElementSibling || item.parentElement !== list) list.insertBefore(item, after || null);
    };
    const end = (ending) => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', end);
      window.removeEventListener('pointercancel', end);
      window.removeEventListener('keydown', escape);
      ghost.remove();
      item.classList.remove('placeholder');
      board.classList.remove('dragging');
      columns.forEach((column) => column.classList.remove('over', 'full'));
      if (ending === 'cancel' || ending.type === 'pointercancel') {
        from.insertBefore(item, next);
        return;
      }
      send(boxIds());
    };
    const escape = (key) => { if (key.key === 'Escape') end('cancel'); };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', end);
    window.addEventListener('pointercancel', end);
    window.addEventListener('keydown', escape);
  };
}
"""

# The page's colours (see streamlit_app.py and .streamlit/config.toml): navy text, teal for the box, grey-blue lines.
_CSS = r"""
.board {display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px;color:#142c43;}
.column {display:flex;flex-direction:column;gap:8px;min-height:150px;padding:10px;border:1px solid #dce3e9;border-radius:14px;background:#edf2f5;transition:border-color .15s,background-color .15s;}
.column.in {border:1.5px dashed #107a72;background:#f3f9f8;}
.column.over {border-color:#107a72;background:#e8f3f2;}
.column.full {border-color:#b4442e;background:#fbefeb;}
.head {display:flex;justify-content:space-between;gap:8px;font-size:14px;font-weight:600;}
.count {color:#516477;font-weight:400;}
.list {display:flex;flex:1;flex-direction:column;gap:6px;margin:0;padding:0;list-style:none;counter-reset:place;}
.list:not(:has(.item))::before {content:attr(data-empty);padding:16px 8px;color:#516477;font-size:13px;text-align:center;}
.item {display:flex;align-items:center;gap:10px;padding:8px 10px;border:1px solid #dce3e9;border-radius:10px;background:#fff;cursor:grab;user-select:none;-webkit-user-select:none;touch-action:pan-y;}
.item:focus-visible {outline:2px solid #107a72;outline-offset:2px;}
.in .item {counter-increment:place;}
.in .item::before {content:counter(place);display:flex;flex:none;align-items:center;justify-content:center;width:22px;height:22px;border-radius:50%;background:#107a72;color:#fff;font-size:12px;font-weight:600;}
.grip {flex:none;padding:6px 4px;color:#8796a5;font-size:18px;line-height:1;touch-action:none;}
.words {display:flex;flex-direction:column;min-width:0;}
.title {overflow:hidden;font-size:14px;font-weight:600;text-overflow:ellipsis;white-space:nowrap;}
.meta {color:#516477;font-size:12.5px;}
.placeholder {opacity:.35;border-style:dashed;}
.ghost {position:fixed;z-index:1000;margin:0;box-shadow:0 8px 24px #142c4333;pointer-events:none;}
.dragging, .dragging * {cursor:grabbing;}
.note {grid-column:1/-1;min-height:1.2em;margin:0;color:#516477;font-size:13px;}
.board:has(.full) .note {color:#b4442e;}
.disabled .item {opacity:.55;cursor:default;}
@media (prefers-reduced-motion: reduce) {.column {transition:none;}}
"""

_box = component('compare_box', css=_CSS, js=_JS)


def compare_box(api):
    """The favorites not in the compare box on the left, the box on the right; while the agent replies
    the box waits. A listing from Home that is not a favorite is only in the box: dragged out, it
    leaves the box."""
    conv = current()
    chosen = conv['compare']
    favorites = favorite_ids()
    working = busy(conv)

    def item(listing_id):
        listing = api.details(listing_id)
        if listing is None:
            return {'id': listing_id, 'title': listing_id, 'meta': t('No longer in the data', '已不在当前数据里')}
        facts = listing.facts
        rent = t(f"SGD {facts['effectiveRentMonthlySgd']:,.0f} / month", f"每月 {facts['effectiveRentMonthlySgd']:,.0f} 新元")
        saved = '' if listing_id in favorites else t(' · not saved', ' · 未收藏')
        return {'id': listing_id, 'title': facts['displayTitle'], 'meta': f'{rent} · {listing_id}{saved}'}

    outside = [item(listing_id) for listing_id in favorites if listing_id not in chosen and api.details(listing_id) is not None]
    inside = [item(listing_id) for listing_id in chosen]
    rev = st.session_state.get('compare-box-rev', 0)
    data = {
        'lists': [
            {'id': 'out', 'title': t('Your favorites', '收藏的房源'), 'items': outside,
             'empty': t('All your favorites are in the box.', '收藏都在比较框里了。') if favorites else t('No favorites yet.', '还没有收藏。')},
            {'id': 'in', 'title': t(f'Compare box (up to {MAX_COMPARED})', f'比较框（最多 {MAX_COMPARED} 套）'), 'items': inside,
             'empty': t('Drag listings here to compare them', '把要比较的房源拖到这里')},
        ],
        'max': MAX_COMPARED,
        'full': t(f'The compare box holds up to {MAX_COMPARED} listings. Take one out first.', f'比较框最多放 {MAX_COMPARED} 套，先拖出一套。'),
        'keyIn': t('Press Enter to put it in the compare box.', '按回车放进比较框。'),
        'keyOut': t('Press Enter to take it out of the compare box.', '按回车移出比较框。'),
        'disabled': working,
        'disabledNote': t('You can change the compare box once the agent has replied.', 'agent 回复后才能调整比较框。'),
        'rev': rev,
    }
    result = _box(data=data, key='compare-box', on_moved_change=lambda: None)
    if isinstance(result.moved, list) and not working:
        # Only listings the box was drawn with, each once, up to three.
        known = {listing['id'] for listing in outside + inside}
        conv['compare'] = [listing_id for listing_id in dict.fromkeys(map(str, result.moved)) if listing_id in known][:MAX_COMPARED]
        st.session_state['compare-box-rev'] = rev + 1
        st.rerun()
