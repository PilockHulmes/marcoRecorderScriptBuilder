# 共享功能部署（阿里云 OSS + 函数计算）

> 2026-11-17 已实际部署并跑通：错误 token 401、上传 200、3 秒内重复写 429、
> 预签名读回价格正确。以下是最终形态。

## 实际部署的东西

```
OSS 桶      maple-trade-560b008d2f   华东1（杭州）  私有
函数计算    服务 maple-trade-share / 函数 share（Python 3.10，128 MB）
HTTP 触发器 https://share-maple-tde-share-nxulewxbuy.cn-hangzhou.fcapp.run
代码       deploy/fc/index.py + ossmin.py（打包 4 KB，零第三方依赖）
```

## 实测决定的设计（和最初的设想不同）

| 试过的 | 结果 | 最终方案 |
|---|---|---|
| 桶设公共读 / 对象设 public-read | 403（RAM 用户没有 PutObjectAcl）| **预签名 URL**（匿名可用，实测 200）|
| PUT 带 `If-Match` 条件写 | 400 `NotImplemented` | 冲突检测放在**函数里**（比对客户端带来的 etag）|
| 函数里用 oss2 | 没有 manylinux wheel，Windows 轮子跑不了 | **纯标准库** `ossmin.py`（V1 签名）|

## 数据流

```
读：客户端 POST /bundle（带 token）
      → 函数返回 index 的预签名 URL + 15 个商人对象的预签名 URL（5 分钟有效）
      → 客户端拿这些 URL 直连 OSS 轮询（1 秒一次也不消耗函数额度）
写：客户端 POST /upload（带 token + 上次看到的 etag）
      → 函数校验 token/字段/限流/etag → 写对象 → 更新 index.json
```

## 函数侧的四道关卡

```
1. token 校验            错误直接 401
2. 字段校验              商人 id 白名单字符、行 key 格式、价格 0~999999、
                         刷新时间 ≤360 秒、体积 ≤2 KB、行数 ≤12
3. 限流                  同一个商人 3 秒内只接受一次（读旧对象判断，无需额外存储）
4. 冲突检测              etag 不一致 → 409，客户端合并后重试
```

## 客户端配置

数据目录下的 `share.json`（已生成，**不进版本库**，里面有 token）：

```json
{
  "endpoint": "https://oss-cn-hangzhou.aliyuncs.com",
  "bucket": "maple-trade-560b008d2f",
  "token": "<见 detections/share_token.txt>",
  "upload_url": "https://<触发器域名>/upload",
  "bundle_url": "https://<触发器域名>/bundle"
}
```

客户端**没有任何 OSS 密钥**，只有这个 token。

## 费用与止损

```
读：直连 OSS 的预签名 GET，按请求计费（约 0.01 元/万次）
写：只写变化的那一个商人，频率 ≈ 每分钟几次
函数：只有 /bundle（5 分钟一次）和 /upload 会调用，免费额度绰绰有余
止损：删除触发器 / 换 SHARE_TOKEN / 阿里云费用预警
```

## 已知限制

- `index.json` 是读-改-写，并发写可能丢一次更新；客户端下次 `/bundle` 会自愈
- 3 秒限流是"同一商人"，恶意刷不同商人仍可绕过（靠费用预警 + 换 token 止损）
- 预签名 URL 有效期 5 分钟；过期后客户端会自动重新 `/bundle`
