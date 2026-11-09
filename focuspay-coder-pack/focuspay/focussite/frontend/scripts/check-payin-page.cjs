// All API calls mocked; serves only the built UI. No production connection.
// Run with NODE_PATH pointing to a directory containing playwright.
const {chromium}=require('playwright');
const {createServer}=require('node:http');
const fs=require('node:fs'), path=require('node:path'), assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../dist');
const server=createServer((req,res)=>{if(req.url.startsWith('/api')){res.writeHead(503);return res.end();}const f=req.url.startsWith('/assets/')?path.join(root,req.url):path.join(root,'panel.html');res.setHeader('Content-Type',f.endsWith('.js')?'text/javascript':f.endsWith('.css')?'text/css':'text/html');try{res.end(fs.readFileSync(f))}catch{res.writeHead(404);res.end()}});
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const base=`http://127.0.0.1:${server.address().port}`;
 const browser=await chromium.launch({headless:true, executablePath:process.env.CHROMIUM_PATH || "/usr/bin/chromium"});
 try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 await page.addInitScript(()=>localStorage.setItem('focuspay_operator_token','mock-ui-only'));
 const a={id:11,order_id:'ui-buy-1',status:'RESERVED',order_status:'AWAITING_CHECK',has_buyer_receipt:true,amount_rub:5200,order_fiat_amount:5200,user_id:123,buyer_first_name:'Тестовый клиент',order_crypto:'btc'};
 const card={id:1,operator_id:1,is_mine:true,operator_display_name:'Тестовый оператор',direction:'payin',method:'sbp',bank:'Тестовый банк',holder_name:'Тестовый получатель',requisites:'0000000000',requisites_masked:'••0000',amount_rub:10000,paid_rub:4800,reserved_rub:5200,free_rub:0,max_checks:2,used_checks:2,checks_left:0,status:'PARTIAL',crypto:'btc',cost_pct:0,allocations:[a]};
 let fail=false, permitted=true; const created=[];const details=[],posts=[],errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',async route=>{
 const u=new URL(route.request().url());if(u.origin!==base)return route.abort();if(!u.pathname.startsWith('/api'))return route.continue();const p=u.pathname;let data={};
 if(route.request().method()==='POST')posts.push(p);
 if(p.endsWith('/auth/operator/me'))data={operator:{id:1,display_name:'UI test',permissions:['payout.requisites',...(permitted?['payout.requisites.confirm']:[])]}};
 else if(p==='/api/operator/payout-requisites'){if(fail)return route.fulfill({status:503,json:{detail:'Test offline'}});if(route.request().method()==='POST'){const body=route.request().postDataJSON();assert.equal(body.direction,'payin');assert.equal(body.amount_rub,10000);assert.equal(body.max_checks,2);const r={...card,...body,id:3,status:'QUEUED',paid_rub:0,reserved_rub:0,allocations:[]};created.push(r);return route.fulfill({json:{requisite:r}});}data={mine:[card,{...card,id:2,direction:'payout',allocations:[]},...created],team:[{...card,id:4,is_mine:false,allocations:undefined,used_checks:null,checks_left:null}],pool_orders:[]};}
 else if(p.endsWith('/payout-requisites/quote'))data={payoff_rub:10000,crypto_amount:0.001,crypto:'btc'};
 else if(/\/payout-requisites\/\d+$/.test(p)){details.push(p);data={requisite:{...card,diagnostics:{computed_at:new Date().toISOString(),readiness:{ready:false,reasons:['Есть назначенный платёж: ждём его завершения']},issuance:{assigned_count:0,paid_count:0,canceled_count:0,first_assigned_at:null,last_assigned_at:null,last_order_id:null,health:'no_data'},traffic:{comparison_windows:35,matching_created:10,matching_paid:6,resolved_orders:9,probability_15m:.1,probability_30m:.2,probability_60m:.3,payment_conversion:6/9,typical_rub:[2500,5000],payment_sequences:[],confidence:'low',source:'fallback',limitations:'Тестовая история, не реальные платежи'}}}};}
 else if(p.endsWith('/3/confirm')){created[0].status='OPEN';data={requisite:created[0]};}
 else if(p.endsWith('/payin_reject')){a.status='CANCELED';a.order_status='CANCELED';card.reserved_rub=0;card.free_rub=5200;data={order:{}};}
 else if(p.endsWith('/users/123'))data={identity:{first_name:'Тестовый клиент'},summary:{total_orders:12},balances:[],recent_orders:[]};
 else if(p.includes('receipt'))return route.fulfill({status:404,json:{detail:'No fixture PDF'}});
 else if(p.endsWith('/orders'))data={orders:[],incoming:[],team_orders:[]};
 return route.fulfill({json:data});});
 await page.goto(base+'/ops/payout-requisites');await page.getByRole('heading',{name:'Приём средств',exact:true}).waitFor();await page.getByText(/Цель 10.*000/).first().waitFor();
 assert.equal(details.length,0);assert.equal(await page.getByText('Поставить карту',{exact:true}).count(),0);
 await page.getByRole('button',{name:/^Проверить ·/}).click();await page.getByRole('button',{name:/Проверить поступление.*Тестовый клиент/}).click();
 const confirm=page.getByRole('button',{name:'Подтвердить поступление рублей',exact:true});await confirm.waitFor();assert(details.every(p=>p.endsWith('/1')));await page.getByText(/Получатель платежа/).waitFor();
 await page.getByRole('button',{name:'Подробнее',exact:true}).first().click();
 await page.getByRole('heading',{name:'Прогноз и диагностика',exact:true}).waitFor();
 await page.getByText('Фактов назначения пока нет',{exact:true}).waitFor();
 await page.getByText('Расчёт, варианты и ограничения',{exact:true}).click();
 await page.getByText('За 30 минут',{exact:true}).waitFor();
 await page.getByRole('button',{name:/Проверить поступление.*Тестовый клиент/}).click();
 await confirm.waitFor();
 await page.screenshot({path:'/tmp/focuspay-payin-desktop.png',fullPage:true});
 for(const width of [390,768,1440]) {
   await page.setViewportSize({width,height:900});
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'viewport overflow '+width);
   await page.keyboard.press('Escape');
   await page.getByRole('dialog',{name:'Проверка платежа'}).waitFor({state:'hidden'});
   const action=page.getByRole('button',{name:'Проверить',exact:true});
   await action.focus();await page.keyboard.press('Enter');await confirm.waitFor();
   await page.screenshot({path:`/tmp/focuspay-payin-${width}.png`,fullPage:true});
 }
 const refresh=()=>page.getByRole('button',{name:'Обновить список',exact:true}).click();
 a.status='PAID';a.order_status='COMPLETED';await refresh();await confirm.waitFor({state:'hidden'});
 a.status='RESERVED';a.order_status='AWAITING_CHECK';await refresh();await confirm.waitFor();
 const reject=page.getByRole('button',{name:'Отклонить чек и отменить заявку',exact:true});page.once('dialog',d=>d.dismiss());await reject.click();assert.equal(posts.length,0);
 page.once('dialog',d=>d.accept());await reject.click();await confirm.waitFor({state:'hidden'});assert(posts.some(p=>p.endsWith('/payin_reject')));
 await page.getByRole('button',{name:/Принимают/}).click();fail=true;await refresh();await page.getByRole('alert').filter({hasText:'Данные устарели'}).waitFor();fail=false;await refresh();await page.getByRole('alert').filter({hasText:'Данные устарели'}).waitFor({state:'hidden'});
 await page.getByRole('button',{name:'Добавить реквизит',exact:true}).click();await page.getByText('Целевая сумма, ₽',{exact:true}).waitFor();await page.setViewportSize({width:390,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'horizontal overflow');await page.screenshot({path:'/tmp/focuspay-payin-mobile.png',fullPage:true});
 const inputs=page.locator('#payout-card-form input');
 await inputs.nth(0).fill('10000');await inputs.nth(1).fill('0000000001');await inputs.nth(2).fill('Банк формы');await inputs.nth(3).fill('Получатель формы');
 await page.getByRole('button',{name:'Поставить карту',exact:true}).click();await page.getByRole('button',{name:'В очередь',exact:true}).click();
 await page.getByRole('button',{name:'Включить',exact:true}).waitFor();assert.equal(created.length,1);assert.equal(created[0].status,'QUEUED');
 await page.getByRole('button',{name:'Включить',exact:true}).click();await page.getByRole('button',{name:'Включить',exact:true}).waitFor({state:'hidden'});assert.equal(created[0].status,'OPEN');

 permitted=false;a.status='RESERVED';a.order_status='AWAITING_CHECK';await page.reload();await page.getByRole('button',{name:/Проверить поступление.*Тестовый клиент/}).click();await page.getByText('Принять чек может старший с правом подтверждения.').waitFor();assert.equal(await confirm.count(),0);assert.deepEqual(errors,[]);
 console.log('PASS: isolated UI, selected-only fetch, updated check, rejection, stale data, mobile, permissions');
 }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1});
