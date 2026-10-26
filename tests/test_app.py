import json, base64, struct, zlib, sys
from playwright.sync_api import sync_playwright

URL = 'file://' + __import__('os').path.abspath(__import__('os').path.join(__import__('os').path.dirname(__file__), '..', 'index.html')) + ''
MOCK = r"""
window.__db={groups:{},expenses:{},settlements:{}};const __subs=[];
window.__push=(col,id,body)=>{ if(body===null) delete __db[col][id]; else __db[col][id]=body; __subs.filter(s=>s.col===col).forEach(s=>s.fire()); };
const __coll=col=>({doc:id=>({set:async b=>{const c=JSON.parse(JSON.stringify(b));__push(col,id,c);window.relay(col,id,c);},delete:async()=>{__push(col,id,null);window.relay(col,id,null);}}),onSnapshot(cb){const s={col,fire:()=>setTimeout(()=>cb({docs:Object.entries(__db[col]).map(([id,b])=>({id,exists:true,data:()=>JSON.parse(JSON.stringify(b))}))}),5)};__subs.push(s);s.fire();return()=>{}}});
window.claude={use:async n=>n==='db'?{collection:__coll}:n==='user'?{me:async()=>({id:window.__uid,name:window.__uname}),can:async()=>true}:null};
"""

def png():
    w, h = 40, 30
    raw = b''.join(b'\x00' + bytes([200, 120, 80] * w) for _ in range(h))
    def chunk(t, d): return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b'')
open('/tmp/tally-r.png', 'wb').write(png())

errors = []
QUEUE = []
def W(ms):
    import time
    end = time.time() + ms / 1000
    while True:
        while QUEUE:
            o, c, i, bd = QUEUE.pop(0)
            if o in pages: pages[o].evaluate('([c,i,b])=>window.__push(c,i,b)', [c, i, bd])
        if time.time() >= end: break
        for pg in list(pages.values()): pg.wait_for_timeout(40)

def check(cond, msg):
    print(('PASS ' if cond else 'FAIL ') + msg)
    if not cond: errors.append(msg)

with sync_playwright() as p:
    b = p.chromium.launch()
    ctxA = b.new_context(viewport={'width': 1360, 'height': 900})
    ctxB = b.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
    pages = {}
    def mk(ctx, name, uid, uname):
        ctx.route('**/fonts.g*/**', lambda r: r.abort())
        ctx.add_init_script(MOCK + f"window.__uid='{uid}';window.__uname='{uname}';")
        pg = ctx.new_page()
        other = 'B' if name == 'A' else 'A'
        def relay(col, id, body):
            QUEUE.append((other, col, id, body))
        pg.expose_function('relay', relay)
        pg.on('console', lambda m: m.type in ('error', 'warning') and print(f'[{name} console {m.type}]', m.text))
        pg.on('pageerror', lambda e: (print(f'[{name} PAGEERROR]', e), errors.append(str(e))))
        pages[name] = pg
        return pg
    A = mk(ctxA, 'A', 'u_arjun', 'Arjun')
    A.goto(URL); W(800)
    ev = lambda pg, js, *a: pg.evaluate(js, *a)

    check(A.locator('#quick-bar').count() == 1, 'overview quick bar shown')
    check('sharing ready' in A.locator('.saved-label').inner_text(), 'sync badge live: ' + A.locator('.saved-label').inner_text())

    # --- quick add from overview
    A.fill('#quick-text', 'Tacos 45 with Alex and Sam yesterday')
    W(100)
    print('  chips:', A.locator('#quick-chips').inner_text().replace('\n', ' | '))
    A.press('#quick-text', 'Enter'); W(500)
    vals = ev(A, "()=>({t:$('#expense-title').value,a:$('#expense-amount').value,g:$('#expense-group').selectedOptions[0].text,d:$('#expense-date').value,c:$('#expense-category').value,p:$$('input[name=participant]:checked').map(x=>x.value)})")
    print('  form:', vals)
    check(vals['t'] == 'Tacos' and vals['a'] == '45' and vals['c'] == 'food' and set(vals['p']) == {'me', 'alex', 'sam'}, 'quick add fills form')
    A.click('#expense-form button.primary'); W(1200)
    e = ev(A, "()=>state.expenses.find(e=>e.title==='Tacos')")
    check(e and e['amount'] == 4500 and sum(e['shares'].values()) == 4500 and len(e['shares']) == 3, 'tacos saved, split 3 ways')

    # parser cases
    for txt in ['Uber 18 paid by Sam', 'Rent 1,800 with everyone in apartment', 'Pizza 32.50 with Mia and Leo', 'coffee $6 with Priya']:
        print('  parse:', txt, '->', json.dumps(ev(A, '(t)=>{const p=parseQuick(t);return {t:p.title,a:p.amount,g:group(p.group).name,payer:p.payer,m:p.members,u:p.unknown,c:p.category}}', txt)))

    # --- shares split + notes + receipt + monthly repeat in the past
    A.click('.heading [data-action=add]'); W(400)
    A.fill('#expense-title', 'Cabin weekend')
    A.fill('#expense-amount', '400')
    A.select_option('#expense-group', label='Lisbon, here we come')
    A.click('[data-mode=shares]'); W(200)
    A.fill('input[name=share-me]', '2'); A.fill('input[name=share-alex]', '1'); A.fill('input[name=share-sam]', '1'); A.fill('input[name=share-mia]', '0')
    print('  summary:', A.locator('#split-summary').inner_text(), '| calc:', A.locator('[data-calc=me]').inner_text())
    A.click('.more-box summary'); A.fill('#expense-notes', 'Booking #A123')
    A.set_input_files('#receipt-input', '/tmp/tally-r.png'); W(500)
    check(A.locator('.receipt-thumb img').count() == 1, 'receipt preview shows')
    d = ev(A, "()=>{const d=new Date();d.setMonth(d.getMonth()-2);return isoDate(d)}")
    A.fill('#expense-date', d)
    A.select_option('#expense-repeat', 'monthly'); W(100)
    print('  repeat note:', A.locator('#repeat-note').inner_text())
    A.click('#expense-form button.primary'); W(1200)
    cab = ev(A, "()=>state.expenses.filter(e=>e.title==='Cabin weekend').map(e=>({id:e.id.slice(-12),date:e.date,shares:e.shares,repeat:e.repeat,lastGen:e.lastGen,rc:!!e.receipt,n:e.notes}))")
    print('  cabin:', cab)
    check(len(cab) == 3 and cab[0]['shares'] == {'me': 20000, 'alex': 10000, 'sam': 10000, 'mia': 0}, 'shares split 2:1:1 and 2 past repeats added')
    check(cab[0]['rc'] and cab[0]['n'] == 'Booking #A123' and not cab[1]['rc'], 'notes + receipt on original only')
    # detail
    A.click('[data-view=activity]'); W(500)
    check(A.locator('.row-tag').count() >= 3, 'row tags shown')
    tid = ev(A, "()=>state.expenses.find(e=>e.title==='Cabin weekend'&&e.repeat).id")
    A.click(f'[data-expense="{tid}"]'); W(500)
    check(A.locator('.repeat-card').count() == 1 and A.locator('#view-receipt').count() == 1 and A.locator('.detail-notes').count() == 1, 'detail shows repeat, note, receipt')
    A.click('#view-receipt'); W(300)
    check(A.locator('.receipt-full').count() == 1, 'receipt enlarges')
    A.click('#back-expense'); W(300)
    A.click('#stop-repeat'); W(500)
    check(ev(A, f"()=>!state.expenses.find(e=>e.id==='{tid}').repeat"), 'stop repeating works')

    # --- insights
    A.click('[data-view=insights]'); W(600)
    check(A.locator('.month-col').count() == 6 and A.locator('.payer-row').count() >= 3, 'insights month chart + payers')
    A.select_option('#insight-group', label='The apartment'); W(500)
    check(A.locator('#insight-group').input_value() != 'all', 'insights group filter')
    A.screenshot(path='/tmp/tally-shot-insights.png', full_page=True)

    # --- payment details + pay + remind
    A.click('#pay-details-btn'); W(300)
    A.fill('#mp-venmo', '@arjun-r'); A.fill('#mp-upi', 'arjun@okicici')
    A.click('#my-pay-form button.primary'); W(400)
    check(ev(A, '()=>state.myPay') == {'venmo': 'arjun-r', 'upi': 'arjun@okicici'}, 'my payment details saved')
    A.click('#quick-groups [data-group=g3]'); W(600)
    check(A.locator('.pay-btn').count() == 1, 'pay button beside Mia')
    A.click('.pay-btn'); W(400)
    check(A.locator('.pay-empty').count() == 1, 'pay modal asks for details')
    A.click('#pay-edit'); W(300); A.fill('#tp-venmo', 'mia-k'); A.fill('#tp-paypal', 'https://paypal.me/miak')
    A.click('#their-pay-form button.primary'); W(400)
    hrefs = A.locator('a.pay-link').evaluate_all('els=>els.map(e=>e.href)')
    print('  pay links:', hrefs)
    check(any('venmo.com/mia-k?txn=pay&amount=46.50' in h for h in hrefs) and any('paypal.me/miak/46.50USD' in h for h in hrefs), 'venmo + paypal links with amount')
    A.screenshot(path='/tmp/tally-shot-pay.png')
    A.click('#pay-record'); W(1000)
    check(ev(A, "()=>balance(group('g3')).me") == 0, 'payment recorded, balance 0')
    # remind tail
    A.click('#quick-groups [data-group=g1]'); W(600)
    A.locator('.remind-btn:not(.pay-btn)').first.click(); W(400)
    txt = A.locator('#nudge-text').input_value()
    print('  remind:', txt.replace('\n', ' / '))
    check('venmo.com/arjun-r' in txt, 'reminder includes pay link')
    A.click('#modal [data-close], #modal .close-btn'); W(300)

    # --- share g1
    A.click('[data-x=share]'); W(400)
    check(A.locator('#share-name').input_value() == 'Arjun', 'share name prefilled')
    A.click('#share-form button.primary'); W(1500)
    sg = ev(A, "()=>state.groups.find(g=>g.shared)")
    check(sg and sg['id'] != 'g1', 'group shared with fresh id')
    check(len(ev(A, '()=>Object.keys(__db.expenses)')) >= 5 and len(ev(A, '()=>Object.keys(__db.groups)')) == 1, 'docs written to shared db')
    check(not any(m['id'] == 'me' for g in ev(A, '()=>Object.values(__db.groups)') for m in g['members']), 'no "me" stored on server')
    print('  badge:', A.locator('.saved-label').inner_text())
    A.screenshot(path='/tmp/tally-shot-shared.png')

    # --- friend joins on phone
    B = mk(ctxB, 'B', 'u_alex', 'Alex')
    B.goto(URL); W(300)
    # load the shared docs into B's store
    ev(B, '(db)=>{for(const c in db)for(const id in db[c])window.__push(c,id,db[c][id])}', ev(A, '()=>__db'))
    W(1200)
    shared_b = ev(B, '()=>state.groups.filter(g=>g.shared).map(g=>g.name)')
    check(shared_b == ['Lisbon, here we come'], 'friend sees shared group')
    check(ev(B, "()=>state.groups.filter(g=>!g.shared).length") == 3, 'friend keeps own sample groups separately')
    B.screenshot(path='/tmp/tally-shot-b-overview.png', full_page=False)
    B.locator('.group-card .share-pill.is-join').first.click(); W(900)
    check(B.locator('.join-pick').count() >= 3, 'join picker offered')
    B.screenshot(path='/tmp/tally-shot-b-join.png')
    B.locator('.join-pick', has_text='Alex').click(); W(1500)
    gidB = ev(B, '()=>state.groups.find(g=>g.shared).id')
    balB = ev(B, '(id)=>balance(group(id)).me', gidB)
    balA = ev(A, '(id)=>balance(group(id))', sg['id'])
    alexId = [m['id'] for m in ev(A, '(id)=>group(id).members', sg['id']) if m['name'] == 'Alex'][0]
    print('  B sees own balance', balB, '| A sees alex', balA[alexId])
    check(balB == balA[alexId], 'friend balance matches from their side')
    check(ev(A, "(id)=>group(id).members.find(m=>m.name==='Alex').claimedBy", sg['id']) == 'u_alex', 'claim synced back to owner')
    # friend adds expense via FAB
    check(B.locator('.fab').is_visible(), 'phone floating add button')
    B.click('.fab'); W(400)
    B.fill('#qa-input', 'Gelato 12 with Arjun')
    B.click('#qa-fill'); W(300)
    print('  B form:', ev(B, "()=>({g:$('#expense-group').selectedOptions[0].text,p:$$('input[name=participant]:checked').map(x=>x.value)})"))
    B.click('#expense-form button.primary'); W(1500)
    gel = ev(A, "()=>state.expenses.find(e=>e.title==='Gelato')")
    print('  A sees gelato:', gel and {'payer': gel['payer'], 'shares': gel['shares']})
    check(gel and gel['shares'].get('me') == 600 and gel['payer'] == alexId, 'friend expense appears for owner with right perspective')
    B.screenshot(path='/tmp/tally-shot-b-detail.png')
    # owner deletes that expense -> gone for friend
    ev(A, "()=>{snapshot();state.expenses=state.expenses.filter(e=>e.title!=='Gelato');save();render();}")
    W(1000)
    check(not ev(B, "()=>state.expenses.some(e=>e.title==='Gelato')"), 'delete syncs to friend')
    # dark + mobile screenshots
    ev(A, "()=>{document.documentElement.dataset.theme='dark'}"); A.click('[data-view=insights]'); W(700)
    A.screenshot(path='/tmp/tally-shot-dark-insights.png', full_page=True)
    A.click('[data-view=overview]'); W(600); A.screenshot(path='/tmp/tally-shot-dark-overview.png')
    B.click('.fab'); W(500); B.click('.more-box summary'); B.screenshot(path='/tmp/tally-shot-b-form.png', full_page=True)
    sw = ev(B, '()=>document.documentElement.scrollWidth')
    check(sw <= 390, f'no horizontal scroll on phone ({sw})')
    b.close()
print('\nFAILURES:', errors if errors else 'none')
