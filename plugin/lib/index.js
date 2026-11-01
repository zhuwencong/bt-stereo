// lib/index.js
// DeepSeek Harness 插件主入口：双音箱左右声道向导
// 纯 JavaScript（无 TypeScript、无运行时依赖）

const GUIDE = `把 Windows 上两只音箱配成一对左右声道的完整流程：

【1. 前提】
- Windows 10/11（macOS / Linux 不支持，依赖 WASAPI）
- 两只音箱都要处于「已连接」状态，不只是「已配对」
- 确认是"两只蓝牙"还是"一只蓝牙 + 一只有线"，后者要做延迟补偿

【2. 安装】
- 普通用户：下载便携版解压双击 bt-stereo.exe，免装 Python
  https://github.com/zhuwencong/bt-stereo/releases/latest
- 源码：git clone 后 pip install numpy comtypes，双击 启动.bat

【3. 先体检】
  python -m bt_stereo --cli doctor
  看结论行：2 只在线可继续；只有 1 只先去 设置→蓝牙和设备 连上第二只。

【4. 配置】
  界面里左声道音箱、右声道音箱各选一只，点「开始」，然后正常放歌。
  程序会自动把系统默认播放设备切到音源端点，停止时恢复。

【5. 延迟对齐】
  有线 + 蓝牙：给有线那侧填 200ms 起步，再按听感微调。
  两只蓝牙：通常 0 即可，不同步时给慢的那只加 20~80ms。

【6. 排障】
  只有一只响 → 点「蓝牙检测」看端点是否在线，再点「试音」判断是软件还是箱子本身
  声音卡顿   → 关掉占带宽的下载/投屏，音箱靠近电脑远离路由器；双蓝牙易受 2.4GHz 干扰
  有回声     → 给听起来慢的那一侧加延迟
  系统声音变了 → 程序切换了默认设备，点「停止」即恢复

仓库：https://github.com/zhuwencong/bt-stereo
国内：https://gitee.com/xingchencong/bt-stereo`;

module.exports = {
  name: 'dsh-plugin-bt-stereo',

  apply(ctx) {
    if (ctx && ctx.logger && typeof ctx.logger.info === 'function') {
      ctx.logger.info('双音箱左右声道向导已加载');
    }

    if (ctx && typeof ctx.command === 'function') {
      // 用户输入 bt-stereo:setup 时返回完整流程
      ctx.command('bt-stereo:setup', () => GUIDE);
    }

    return GUIDE;
  },
};
