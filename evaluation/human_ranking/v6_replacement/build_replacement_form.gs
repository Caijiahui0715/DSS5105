/**
 * 新建一个只有 A08、A09、B01、G04 四道题的 Google 表单，规则和 V6 完全一样。
 *
 * 题目结构照抄 V6：第 1 页填 Reviewer code；之后每题一页，依次是题目文字、对比图、
 * 每个候选一道单选名次题（数字名次 + Cannot judge，允许并列）、一道选填理由。
 * 题目标题的写法也和 V6 一致（"A08 | Candidate A rank"），以后两份表单的回答可以按
 * Reviewer code 直接拼在一起。
 *
 * 用法：
 * 1. 把 A08.png、A09.png、B01.png、G04.png 上传到 Google Drive 的同一个文件夹。
 * 2. 打开 https://script.google.com ，新建项目，粘贴本文件全部内容。
 * 3. 把 FOLDER_ID 换成那个文件夹的 ID（文件夹网址 /folders/ 后面那一串）。
 * 4. 函数选 buildReplacementForm，点"运行"，按提示授权。
 * 5. 执行日志里会打印新表单的编辑链接和填写链接。
 */

const FOLDER_ID = 'PASTE_YOUR_DRIVE_FOLDER_ID_HERE';

const TITLE = 'DSS5105 Human Listing Ranking V6 (Desktop) - Part 2';
const DESCRIPTION = 'Evaluate ranking only, not hard-constraint eligibility. ' +
    'Review the comparison image (click to enlarge) and rank the listings. Equal ranks indicate ties.\n\n' +
    'Please use the same reviewer code as in Part 1.';

const CASES = [
  {id: 'A08', n: 5,
   query: 'I need a whole unit of at least 80 square metres, with rent capped at SGD 7,000. Rank by larger space first, then a shorter MRT walk, then lower rent.'},
  {id: 'A09', n: 5,
   query: "Find a room for at most SGD 1,500, within 1 km of at least 30 food places and no more than 1,000 metres' walk from the nearest operating MRT. Prioritise more food options, then a shorter MRT walk."},
  {id: 'B01', n: 3,
   query: 'I need a room for at most SGD 1,300 where full cooking, including frying, is definitely allowed.'},
  {id: 'G04', n: 5,
   query: "My budget stays the same, but I'm also open to shared accommodation."},
];
const LABELS = 'ABCDE';

function buildReplacementForm() {
  if (FOLDER_ID.indexOf('PASTE') === 0) {
    throw new Error('请先把 FOLDER_ID 换成存放图片的 Drive 文件夹 ID。');
  }
  const folder = DriveApp.getFolderById(FOLDER_ID);
  const blobs = CASES.map(function (c) {
    const files = folder.getFilesByName(c.id + '.png');
    if (!files.hasNext()) throw new Error('文件夹里找不到图片：' + c.id + '.png');
    return files.next().getBlob();
  });

  const form = FormApp.create(TITLE);
  form.setDescription(DESCRIPTION).setProgressBar(true).setCollectEmail(false);

  form.addTextItem().setTitle('Reviewer code (not your name)').setRequired(true);

  CASES.forEach(function (c, i) {
    form.addPageBreakItem().setTitle(c.id + ' — Listing ranking');
    form.addSectionHeaderItem().setTitle(c.query).setHelpText('Candidates were preliminarily screened; rank only.');
    form.addImageItem().setTitle('User profile and side-by-side listing facts (click to enlarge)').setImage(blobs[i]);

    const choices = [];
    for (let k = 1; k <= c.n; k++) choices.push(String(k));
    choices.push('Cannot judge');
    for (let k = 0; k < c.n; k++) {
      form.addMultipleChoiceItem()
          .setTitle(c.id + ' | Candidate ' + LABELS[k] + ' rank')
          .setChoiceValues(choices)
          .setRequired(true);
    }
    form.addParagraphTextItem().setTitle(c.id + ' | Ranking rationale / ties / missing information (optional)');
  });

  Logger.log('编辑链接：' + form.getEditUrl());
  Logger.log('填写链接：' + form.getPublishedUrl());
}
