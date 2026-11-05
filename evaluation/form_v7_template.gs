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

const CASES = /*CASES*/[];

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
