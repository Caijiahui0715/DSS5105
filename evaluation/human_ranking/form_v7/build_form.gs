/**
 * DSS5105 房源人工排序（V7）—— 建表单脚本
 *
 * 由 evaluation/form_v7.py 生成，不要手改 CASES；要改题目请改 Python 后重新生成。
 *
 * 用法：
 * 1. 把 images/ 里的 15 张 PNG 上传到 Google Drive 的一个文件夹。
 * 2. 打开 https://script.google.com ，新建项目，把本文件全部内容粘贴进去。
 * 3. 把下面的 FOLDER_ID 换成那个文件夹的 ID（文件夹网址 /folders/ 后面那一串）。
 * 4. 选中函数 buildForm，点"运行"，按提示授权。
 * 5. 运行完在"执行日志"里找到编辑链接和填写链接。
 *
 * 每运行一次就新建一个表单，不会改动已有表单。
 */

const FOLDER_ID = 'PASTE_YOUR_DRIVE_FOLDER_ID_HERE';
const TITLE = 'DSS5105 房源人工排序（V7）';

const DESCRIPTION = [
  '感谢参与。每道题给出一位用户的租房需求和 3–5 套候选房源。',
  '候选房源已经按用户的硬条件筛过，请只按用户说的排序要求给它们排名：第 1 名是最符合的。',
  '',
  '· 每个名次只能给一套候选，每套候选只能选一个名次。',
  '· 用户说了多个排序要求时，按先后顺序比较：前一项相同，才比较下一项。',
  '· 用户没说排序要求时，按租金从低到高。',
  '· 通勤时间指公共交通到 NUS 商学院，工作日 08:30 出发。',
  '· "未注明"表示数据里没有写这一项，不代表"没有"。',
  '· 实在无法判断，就勾选"这题无法判断"，排名网格可以留空。',
  '',
  '大约需要 15–20 分钟。请不要填写真实姓名。',
].join('\n');

const CASES = [
  {
    "id": "A01",
    "query": "我要找 D05 区的普通房，月租不超过 1,200 新元。在所有符合条件的房间里，租金便宜的排前面。\n\n英文原文：I need a common room in D05 for no more than SGD 1,200 per month. Among all eligible rooms, rank the cheaper ones first.",
    "image": "A01.png",
    "labels": [
      "A",
      "B",
      "C",
      "D"
    ]
  },
  {
    "id": "A02",
    "query": "我是女学生，想找一间有家具的房间，月租最多 1,400 新元。能做饭和有空调都是必须的。\n\n英文原文：I am a female student looking for a furnished room up to SGD 1,400 per month. Cooking and air-conditioning are both must-haves.",
    "image": "A02.png",
    "labels": [
      "A",
      "B",
      "C"
    ]
  },
  {
    "id": "A04",
    "query": "我想整租一套 condo 或私人公寓，月租最多 6,000 新元，至少 2 个浴室。先按到学院的通勤时间从短到长排，再按租金从低到高排。\n\n英文原文：I want to rent a whole condo or private apartment for at most SGD 6,000, with at least 2 bathrooms. Rank the results by shortest commute to my faculty first, then lower rent.",
    "image": "A04.png",
    "labels": [
      "A",
      "B",
      "C"
    ]
  },
  {
    "id": "A05",
    "query": "给我看有家具、有空调的主人房，月租不超过 1,800 新元。\n\n英文原文：Show me furnished master rooms with air-conditioning, at no more than SGD 1,800 per month.",
    "image": "A05.png",
    "labels": [
      "A",
      "B",
      "C"
    ]
  },
  {
    "id": "A08",
    "query": "我要整租一套至少 80 平方米的房子，月租上限 7,000 新元。先按面积从大到小排，再按到地铁站步行从近到远排，最后按租金从低到高排。\n\n英文原文：I need a whole unit of at least 80 square metres, with rent capped at SGD 7,000. Rank by larger space first, then a shorter MRT walk, then lower rent.",
    "image": "A08.png",
    "labels": [
      "A",
      "B",
      "C",
      "D",
      "E"
    ]
  },
  {
    "id": "A09",
    "query": "帮我找一间月租最多 1,500 新元的房间，1 公里内至少有 30 家餐饮，离最近的运营中地铁站步行不超过 1,000 米。优先餐饮选择多的，其次到地铁站步行近的。\n\n英文原文：Find a room for at most SGD 1,500, within 1 km of at least 30 food places and no more than 1,000 metres' walk from the nearest operating MRT. Prioritise more food options, then a shorter MRT walk.",
    "image": "A09.png",
    "labels": [
      "A",
      "B",
      "C",
      "D",
      "E"
    ]
  },
  {
    "id": "B01",
    "query": "我要一间月租最多 1,300 新元的房间，必须明确允许正常做饭，包括煎炒。\n\n英文原文：I need a room for at most SGD 1,300 where full cooking, including frying, is definitely allowed.",
    "image": "B01.png",
    "labels": [
      "A",
      "B",
      "C"
    ]
  },
  {
    "id": "B02",
    "query": "帮我找一间月租最多 1,500 新元的房间，但房东不能和我住在同一套房子里。\n\n英文原文：Find me a room up to SGD 1,500, but the landlord must not live in the same home.",
    "image": "B02.png",
    "labels": [
      "A",
      "B",
      "C"
    ]
  },
  {
    "id": "B03",
    "query": "我要一间有空调的房间，月租不高于 1,500 新元。\n\n英文原文：I need an air-conditioned room with rent no higher than SGD 1,500.",
    "image": "B03.png",
    "labels": [
      "A",
      "B",
      "C"
    ]
  },
  {
    "id": "B06",
    "query": "我是女性租客，找一间月租不超过 1,400 新元的房间。把明确接受女性的房源，和没写性别要求的房源分开列出来。\n\n英文原文：I am a female tenant looking for a room at or below SGD 1,400. Only show confirmed compatible listings separately from listings whose tenant-gender rule is not stated.",
    "image": "B06.png",
    "labels": [
      "A",
      "B",
      "C"
    ]
  },
  {
    "id": "G01",
    "query": "第 1 轮：我的预算是每月 1,500 新元，想找一间靠近 NUS 的房间。\n第 2 轮：我可以把预算提高到 1,800 新元。其他要求都不变。\n\n英文原文：\nTurn 1: My budget is SGD 1,500 per month, and I'm looking for a room near NUS.\nTurn 2: I can increase my budget to SGD 1,800. Please keep all my other requirements unchanged.\n\n请按最后一轮之后的条件排序。",
    "image": "G01.png",
    "labels": [
      "A",
      "B",
      "C"
    ]
  },
  {
    "id": "G02",
    "query": "第 1 轮：帮我找一间月租低于 1,600 新元的房间。价格是我最看重的。\n第 2 轮：现在通勤时间比价格更重要，但预算保持不变。\n\n英文原文：\nTurn 1: Find me a room with a monthly rent below SGD 1,600. Price is my top priority.\nTurn 2: Commute time is now more important than price, but please keep my budget unchanged.\n\n请按最后一轮之后的条件排序。",
    "image": "G02.png",
    "labels": [
      "A",
      "B",
      "C"
    ]
  },
  {
    "id": "G03",
    "query": "第 1 轮：我需要一间能做饭、有空调的房间。\n第 2 轮：能不能做饭对我不重要了，但空调仍然必须有。\n\n英文原文：\nTurn 1: I need a room where cooking is allowed and air conditioning is available.\nTurn 2: Cooking is no longer important to me, but air conditioning is still a must.\n\n请按最后一轮之后的条件排序。",
    "image": "G03.png",
    "labels": [
      "A",
      "B",
      "C"
    ]
  },
  {
    "id": "G04",
    "query": "第 1 轮：我在找一套整租的 apartment，每月预算 3,000 新元。\n第 2 轮：预算不变，但我也可以接受合租。\n\n英文原文：\nTurn 1: I'm looking for an entire apartment with a monthly budget of SGD 3,000.\nTurn 2: My budget stays the same, but I'm also open to shared accommodation.\n\n请按最后一轮之后的条件排序。",
    "image": "G04.png",
    "labels": [
      "A",
      "B",
      "C",
      "D",
      "E"
    ]
  },
  {
    "id": "G05",
    "query": "第 1 轮：我的预算是 1,800 新元，想住得离 NUS 比较近。\n第 2 轮：其实我的预算应该是 1,500 新元，而且通勤最好不超过 30 分钟。\n\n英文原文：\nTurn 1: My budget is SGD 1,800, and I'd like to live relatively close to NUS.\nTurn 2: Actually, my budget should be SGD 1,500, and I'd prefer a commute of no more than 30 minutes.\n\n请按最后一轮之后的条件排序。",
    "image": "G05.png",
    "labels": [
      "A",
      "B",
      "C"
    ]
  }
];

function buildForm() {
  if (FOLDER_ID.indexOf('PASTE') === 0) {
    throw new Error('请先把 FOLDER_ID 换成存放图片的 Drive 文件夹 ID。');
  }
  const folder = DriveApp.getFolderById(FOLDER_ID);
  const blobs = CASES.map(function (c) {
    const files = folder.getFilesByName(c.image);
    if (!files.hasNext()) throw new Error('文件夹里找不到图片：' + c.image);
    return files.next().getBlob();
  });

  const form = FormApp.create(TITLE);
  form.setDescription(DESCRIPTION)
      .setProgressBar(true)
      .setCollectEmail(false)
      .setShuffleQuestions(false)
      .setConfirmationMessage('已提交，谢谢！');

  form.addTextItem()
      .setTitle('评审编号（不要填真实姓名）')
      .setHelpText('例如 R01。同一个人请始终用同一个编号。')
      .setRequired(true);

  CASES.forEach(function (c, i) {
    form.addPageBreakItem().setTitle(c.id + '（第 ' + (i + 1) + ' / ' + CASES.length + ' 题）');
    form.addSectionHeaderItem().setTitle('用户需求').setHelpText(c.query);
    form.addImageItem()
        .setTitle('候选房源对比')
        .setHelpText('看不清时可以用浏览器放大（Ctrl/⌘ 加 +）。')
        .setImage(blobs[i])
        .setAlignment(FormApp.Alignment.CENTER);

    const ranks = c.labels.map(function (_, k) { return '第 ' + (k + 1) + ' 名'; });
    const grid = form.addGridItem()
        .setTitle(c.id + ' 排名')
        .setHelpText('每行一套候选，每列一个名次。每列只能选一个，不能并列。')
        .setRows(c.labels.map(function (l) { return '候选 ' + l; }))
        .setColumns(ranks);
    grid.setValidation(FormApp.createGridValidation()
        .setHelpText('每个名次只能给一套候选。')
        .requireLimitOneResponsePerColumn()
        .build());

    form.addCheckboxItem()
        .setTitle(c.id + ' 无法判断')
        .setChoiceValues(['这题无法判断（勾选后排名网格可以留空）']);
    form.addParagraphTextItem()
        .setTitle(c.id + ' 排序理由 / 缺少的信息（选填）');
  });

  Logger.log('编辑链接：' + form.getEditUrl());
  Logger.log('填写链接：' + form.getPublishedUrl());
}
