// V6: Upload all PNG images from the images folder into ONE Google Drive folder.
// Paste that folder's ID below. The script uses its PNG files to create the forms.
const IMAGE_FOLDER_ID = "PASTE_GOOGLE_DRIVE_FOLDER_ID_HERE";
const CASES = [{"id":"A01","en":"I need a common room in D05 for no more than SGD 1,200 per month. Among all eligible rooms, rank the cheaper ones first.","zh":"我想在新加坡房地产第05区（D05）找一间普通房，月租不超过1200新币，价格越便宜越好。","n":3,"letters":["A","B","C"]},{"id":"A02","en":"I am a female student looking for a furnished room up to SGD 1,400 per month. Cooking and air-conditioning are both must-haves.","zh":"我是女生，想找月租不超过1400新币的带家具房间，必须能做饭而且有空调。","n":3,"letters":["A","B","C"]},{"id":"A04","en":"I want to rent a whole condo or private apartment for at most SGD 6,000, with at least 2 bathrooms. Rank the results by shortest commute to my faculty first, then lower rent.","zh":"我想整租公寓或私人公寓，预算最多6000新币，至少两个卫生间。优先考虑到我学院通勤更快的，再看租金。","n":3,"letters":["A","B","C"]},{"id":"A05","en":"Show me furnished master rooms with air-conditioning, at no more than SGD 1,800 per month.","zh":"想找有家具和空调的主人房，月租不超过1800新币。","n":3,"letters":["A","B","C"]},{"id":"A08","en":"I need a whole unit of at least 80 square metres, with rent capped at SGD 7,000. Rank by larger space first, then a shorter MRT walk, then lower rent.","zh":"想整租至少80平方米的房子，月租最多7000新币。面积越大越好，其次希望离地铁近、租金低。","n":3,"letters":["A","B","C"]},{"id":"A09","en":"Find a room for at most SGD 1,500, within 1 km of at least 30 food places and no more than 1,000 metres' walk from the nearest operating MRT. Prioritise more food options, then a shorter MRT walk.","zh":"我想找1500新币以内的房间，附近1公里至少有30家餐饮店，步行到已运营地铁站不超过1000米。餐饮选择多的优先，其次看地铁距离。","n":3,"letters":["A","B","C"]},{"id":"B01","en":"I need a room for at most SGD 1,300 where full cooking, including frying, is definitely allowed.","zh":"我想找1300新币以内的房间，必须明确允许完整烹饪，包括煎炒。","n":3,"letters":["A","B","C"]},{"id":"B02","en":"Find me a room up to SGD 1,500, but the landlord must not live in the same home.","zh":null,"n":3,"letters":["A","B","C"]},{"id":"B03","en":"I need an air-conditioned room with rent no higher than SGD 1,500.","zh":null,"n":3,"letters":["A","B","C"]},{"id":"B06","en":"I am a female tenant looking for a room at or below SGD 1,400. Only show confirmed compatible listings separately from listings whose tenant-gender rule is not stated.","zh":null,"n":3,"letters":["A","B","C"]},{"id":"G01","en":"I can increase my budget to SGD 1,800. Please keep all my other requirements unchanged.","zh":"我预算1500新币，想在NUS附近找房间。后来预算可以提高到1800，其他条件不变。","n":3,"letters":["A","B","C"]},{"id":"G02","en":"Commute time is now more important than price, but please keep my budget unchanged.","zh":"先找1600新币以下的房间，价格最重要。后来我更在意通勤时间，预算不变。","n":3,"letters":["A","B","C"]},{"id":"G03","en":"Cooking is no longer important to me, but air conditioning is still a must.","zh":"我想找允许做饭、有空调的房间。后来做饭不重要了，但必须保留空调。","n":3,"letters":["A","B","C"]},{"id":"G04","en":"My budget stays the same, but I'm also open to shared accommodation.","zh":"我想整租公寓，预算3000新币。后来合租也可以考虑，预算不变。","n":3,"letters":["A","B","C"]},{"id":"G05","en":"Actually, my budget should be SGD 1,500, and I'd prefer a commute of no more than 30 minutes.","zh":"预算1800新币，想住得离NUS近。后来预算改为1500，最好30分钟内到学校。","n":3,"letters":["A","B","C"]}];
function createDSS5105RankingV6() {
 if (IMAGE_FOLDER_ID.includes('PASTE_')) throw new Error('Please set IMAGE_FOLDER_ID first.');
 const folder=DriveApp.getFolderById(IMAGE_FOLDER_ID);
 const images={};const iter=folder.getFiles();
 while(iter.hasNext()){const f=iter.next();images[f.getName()]=f;}
 for(const lang of ['en','zh']){
  const zh=lang==='zh';
  const form=FormApp.create(zh?'DSS5105 人工房源排序 V6（桌面版）':'DSS5105 Human Listing Ranking V6 (Desktop)');
  form.setDescription(zh?'仅评价房源排序，不负责核验硬约束。请查看横向对比图（可点击放大），为候选房源排序；同名次表示并列。':'Evaluate ranking only, not hard-constraint eligibility. Review the comparison image (click to enlarge) and rank the listings. Equal ranks indicate ties.');
  form.setCollectEmail(false);
  form.addTextItem().setTitle(zh?'评估者编号（不填写姓名）':'Reviewer code (not your name)').setRequired(true);
  CASES.forEach(c=>{
   const file=images[c.id+'_'+lang+'.png'];if(!file)throw new Error('Missing image '+c.id+'_'+lang+'.png');
   form.addPageBreakItem().setTitle(c.id+' — '+(zh?'房源排序':'Listing ranking'));
   form.addSectionHeaderItem().setTitle(zh?c.zh:c.en).setHelpText(zh?'以下候选已做后台初步资格核验；你只需判断排序。':'Candidates were preliminarily screened; rank only.');
   form.addImageItem().setTitle(zh?'用户画像及房源横向对比（点击图片放大）':'User profile and side-by-side listing facts (click to enlarge)').setImage(file.getBlob());
   c.letters.forEach(letter=>form.addMultipleChoiceItem().setTitle(c.id+' | '+(zh?'候选 ':'Candidate ')+letter+(zh?' 名次':' rank')).setChoiceValues(Array.from({length:c.n},(_,i)=>String(i+1)).concat([zh?'无法判断':'Cannot judge'])).setRequired(true));
   form.addParagraphTextItem().setTitle(c.id+' | '+(zh?'排序依据／并列原因／信息不足（选填）':'Ranking rationale / ties / missing information (optional)')).setRequired(false);
  });
  Logger.log((zh?'中文':'English')+' EDIT: '+form.getEditUrl());
  Logger.log((zh?'中文':'English')+' RESPOND: '+form.getPublishedUrl());
 }
}
