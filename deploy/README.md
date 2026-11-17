# 共享功能部署（阿里云 OSS + 函数计算）

> 状态：代码已就绪，**账号侧还没打通**——用现在的 AccessKey 创建桶返回
> `UserDisable`（账号未开通/未实名/欠费）。先把账号弄好，再按下面步骤走。

## 0. 一次性准备

1. 登录阿里云 → 开通 **OSS**（对象存储）与 **函数计算 FC**
2. 完成实名认证、确认没有欠费
3. 建一个桶，建议：

```
地域：华东1（杭州）（实测延迟 45~60 ms，最快）
名称：maple-trade-share-<6 位随机>
读写权限：私有
版本控制：开启（写坏了能回滚）
```

## 1. 建 RAM 用户（只给最小权限）

函数计算要用一把只能写 `merchants/` 和 `index.json` 的密钥：

```json
{
  "Version": "1",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["oss:GetObject", "oss:PutObject", "oss:HeadObject"],
      "Resource": [
        "acs:oss:*:*:<桶名>/merchants/*",
        "acs:oss:*:*:<桶名>/index.json"
      ]
    }
  ]
}
```

**不要把主账号 AccessKey 放进任何地方。**

## 2. 部署函数

```
函数计算 → 新建函数 → 类型选「HTTP 函数」→ Python 3.10
代码：deploy/fc/index.py
依赖：oss2（在"层"或函数里 pip install oss2 -t .）
```

环境变量（函数配置里填）：

```
OSS_ENDPOINT   https://oss-cn-hangzhou.aliyuncs.com
OSS_BUCKET     <桶名>
OSS_KEY_ID     <RAM 用户 AccessKeyId>
OSS_KEY_SECRET <RAM 用户 AccessKeySecret>
SHARE_TOKEN    <共享口令，长随机串>
```

触发器：HTTP 触发器，方法只留 POST，鉴权选「无需签名」（我们自己用 token）。

## 3. 让客户端能匿名读

共享的只有游戏价格，公开读没有风险，而且能让 1 秒轮询不消耗函数额度：

```
方式 A：把 merchants/ 和 index.json 设为「公共读」
方式 B（更稳）：给桶开 CDN，用 CDN 域名做 read_prefix
```

## 4. 客户端配置

在数据目录放 `share.json`（`%LOCALAPPDATA%\MapleTrade\data\` 或 exe 旁的 `data\`）：

```json
{
  "endpoint": "https://oss-cn-hangzhou.aliyuncs.com",
  "bucket": "maple-trade-share-xxxxxx",
  "token": "<共享口令>",
  "upload_url": "https://<函数 HTTP 地址>/upload",
  "read_prefix": "https://<桶名>.oss-cn-hangzhou.aliyuncs.com"
}
```

**客户端里没有 OSS 密钥**，只有这个 token；写请求全部经函数校验。

## 5. 费用与止损

```
OSS 请求：读 0.01 元/万次量级，写入更少；30 人全活跃也就每天 < 1 元
函数计算：写入频率低（3 分钟才刷新一次），免费额度足够
关掉方式：删掉函数触发器 / 换 SHARE_TOKEN / 关函数
预警：阿里云「费用预警」设 10 元/月，短信通知
```

## 6. 已知限制

- 中转的限流是**无状态**的：只靠"同一个商人 3 秒内只收一次"（读旧对象判断），
  不依赖额外存储；恶意刷不同商人仍可绕过，靠费用预警和 token 轮换止损
- `index.json` 是读-改-写，并发写可能丢一次更新——客户端下次拉取会自愈
