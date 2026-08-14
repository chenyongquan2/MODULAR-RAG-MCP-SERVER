# 金标判定人工抽检表（24 条）

> **怎么用**：对每条问自己一句 —— **「只读这段 chunk，能回答这个问题吗？」**
> 能（哪怕只答了一部分）→ 判**相关**；不能 → 判**不相关**。
> 然后在下方「填这里」写 `Y`（你认为相关）或 `N`（你认为不相关）。
>
> 注意判的是**能否回答问题**，不是「文字像不像答案」—— 一段复述问题措辞却不含
> 信息的文字应判 N。这正是第二代金标与第一代（纯 embedding 相似度）的差别。
>
> 填完把结果按末尾的对照表抄进 `tests/fixtures/labeling_sample_zh.json` 的
> `human_label` 字段（`true`/`false`），再跑 `--import-sample`。

**LLM 判定分布**：接受 12 条 / 拒绝 12 条（分层抽样，各半）

---

## 01

**问题**：在 IMTServerAPI::FeederGet 中，配置数据复制的具体操作是什么？

**Chunk**：Python  | | | --- | | AdminAPI.FeederNext(    pos            # 配置的位置    ) |  参数  pos  [in]  配置的位置，从 0 开始。  feeder  [out]  数据源配置的对象。必须先使用 [IMTAdminAPI::FeederCreate](imtadminapi_feedercreate.htm) 方法创建该数据源对象。  返回值  成功执行的标志是 [MT_RET_OK](retcodes_successful.htm) 响应代码。否则将返回错误代码。  注意  该方法将具有指定索引的源的配置数据复制到数据源对象。  ###### FeederGet  FeederGet

**LLM**：**接受**（认为相关），分级 `3 直接回答`
**理由**：The passage directly states that the method copies the configuration data of the source with the specified index to the data source object, matching the reference answer.

**填这里**： `[ ]`

---

## 02

**问题**：账户组交易的作用是什么？

**Chunk**：交易盈利  选定时段的详细交易报告。它由多个图表组成：根据交易量、根据盈利和亏损交易的分布、根据盈利、亏损、总数和其他指标。  ![“交易盈利”报告](deals_profit.png "“交易盈利”报告")  过滤器  可以过滤为报告请求的数据。在经理端请求报告之前，指定以下参数：  * 组 — 包含账户的组，在该账户上必须创建报告。您可以指定一个或多个用逗号分隔的账户。 * 时段 — 将生成报告的时段的开始和结束日期。 * Lead campaign（潜在客户活动） — 吸引执行交易的客户的广告宣传活动的名称。 * Lead source（潜在客户源） — 执行交易的客户来源的网站。  报告中的图表  该报告包括多个图表：  * 交易量 — 总交易量、盈利交易量和亏损交易量的分布情况。 * 盈利额 — 交易盈亏的分布情况。 * 盈利交易数 — 盈亏交易数量的分布情况。 * 盈利交易量平均值 — 盈亏交易的平均交易量分布。 * …

**LLM**：拒绝（认为不相关），分级 `1 沾边`
**理由**：The passage mentions groups and trading in the context of a profit report, but does not contain any information about the function of account group trading or the related APIs.

**填这里**： `[ ]`

---

## 03

**问题**：只能在主服务器上运行的应用程序才能添加或更新配置吗？

**Chunk**：只能从主服务器上运行的插件添加或更新配置。对于所有其他插件，将返回响应代码 [MT_RET_ERR_NOTMAIN](retcodes_api.htm) 。  添加前会检查记录的正确性。如果记录有误，则将返回错误代码 [MT_RET_ERR_PARAMS](retcodes_common.htm) 。  ###### GatewayDelete  GatewayDelete

**LLM**：**接受**（认为相关），分级 `3 直接回答`
**理由**：The passage directly states that configurations can only be added or updated from the main server and returns the specified error code for others.

**填这里**： `[ ]`

---

## 04

**问题**：交易品种组在假期里允许客户进行哪些操作？

**Chunk**：IMTConHoliday::SymbolShift  更改假期适用的 [交易品种](config_symbol.htm) 列表中的交易品种位置。  C++  | | | --- | | MTAPIRES  IMTConHoliday::SymbolShift(    const UINT  pos,       // 交易品种的位置    const int   shift      // 移动    ) |  C++  | | | --- | | MTRetCode  CIMTConHoliday.SymbolShift(    uint        pos,       // 交易品种的位置    int         shift      // 移动    ) |  参数  pos  [in]  列表中交易品种的位置，从 0 开始。  shift  [in]  从其当前位置移位。负值表示移动到列表的顶部，正值表示移动 …

**LLM**：拒绝（认为不相关），分级 `1 沾边`
**理由**：The passage mentions holidays and trading symbols but only describes an API method for shifting symbol positions, not the client operations allowed during holidays.

**填这里**： `[ ]`

---

## 05

**问题**：IMTAdminAPI 接口在 MTAdminCreate 中的输出参数起什么作用？

**Chunk**：注意  该请求可以轻松安排结果交易的分页输出。通过在“总计”参数下进行设置，确定应在一页中显示的交易数量。然后找到每个页面的'offset'参数，第一页从0开始。  该方法无法从事件处理程序（任何 IMT*Sink 类方法）中调用。  ###### DealAdd  DealAdd  | | | | | | | --- | --- | --- | --- | --- | | | | | | | --- | --- | | [Manager API](managerapi.htm) / [管理员接口](imtadminapi.htm) / [交易数据库](imtadminapi_trading.htm) / [交易](imtadminapi_trading_deal.htm) / DealAdd | [Previous](imtadminapi_dealrequestpage.htm)  [Next](imtadminapi_de …

**LLM**：拒绝（认为不相关），分级 `0 无关`
**理由**：The passage discusses IMTAdminAPI::DealAdd and pagination, which is completely irrelevant to the output parameters of MTAdminCreate.

**填这里**： `[ ]`

---

## 06

**问题**：IMTAdminAPI 接口在 MTAdminCreate 中的输出参数起什么作用？

**Chunk**：参数  name  [in]  参数名称。  param  [out]  报告参数的对象。'param'对象必须先使用 [IMTAdminAPI::ReportParamCreate](imtadminapi_reportparamcreate.htm) 方法来创建。  返回值  成功执行的指示是 [MT_RET_OK](retcodes_successful.htm) 响应代码。否则，将返回错误代码。  注  [IMTConParam::Name](imtconparam_name.htm) 值用作参数名称。  ##### InputTotal  InputTotal

**LLM**：拒绝（认为不相关），分级 `1 沾边`
**理由**：The passage mentions IMTAdminAPI and output parameters, but it describes a different function (ReportParamCreate) and does not mention MTAdminCreate or its output parameter.

**填这里**： `[ ]`

---

## 07

**问题**：在 IMTServerAPI::FeederGet 中，配置数据复制的具体操作是什么？

**Chunk**：#### IMTConFeeder  MTConFeeder  | | | | | | | --- | --- | --- | --- | --- | | | | | | | --- | --- | | [配置接口](reference_configurations.htm) / [数据源](config_datafeeds.htm) / IMTConFeeder | [Previous](config_datafeeds.htm)  [Next](imtconfeeder_enum.htm) | | |  IMTConFeeder  IMTConFeeder 接口包含用来配置数据源的方法。

**LLM**：拒绝（认为不相关），分级 `1 沾边`
**理由**：The passage mentions the IMTConFeeder interface for configuring data sources but does not mention FeederGet or the specific data copying operation described in the answer.

**填这里**： `[ ]`

---

## 08

**问题**：交易品种组在假期里允许客户进行哪些操作？

**Chunk**：| CONDITION_PROFIT | 2005 | 该参数允许根据客户的当前浮动利润使用规则。 | | CONDITION_DAILY_DEALS | 3000 | 该参数允许根据当前和前几天（包括周末和假期）客户的交易数目使用规则。 | | CONDITION_DAILY_DEALS_PERIOD | 3001 | 某日交易的频率。基于最后8笔交易计算（交易之间的平均时间）。 | | CONDITION_DAILY_PROFIT | 3002 | 当前和前几天（包括周末和假期）正被处理请求的客户的利润。 | | CONDITION_POSITION_VOLUME | 4000 | 已到达请求所针对的交易品种持仓的当前量。 | | CONDITION_POSITION_PROFIT | 4001 | 已到达请求所针对的交易品种持仓的当前利润。 | | CONDITION_POSITION_AGE | 4002 | 使用该参数 …

**LLM**：拒绝（认为不相关），分级 `0 无关`
**理由**：该段落讨论了交易条件参数，并未提及假期期间允许客户进行哪些操作。

**填这里**： `[ ]`

---

## 09

**问题**：IMTAdminAPI 接口在 MTAdminCreate 中的输出参数起什么作用？

**Chunk**：CMTManagerAPIFactory::CreateAdmin  Create the administrator interface [IMTAdminAPI](imtadminapi.htm).  C++  | | | --- | | MTAPIRES  CMTManagerAPIFactory::CreateAdmin(    UINT           version,     // Version    IMTAdminAPI**  admin        // A pointer to the administrator interface    ) |  .NET  | | | --- | | CIMTAdminAPI  SMTManagerAPIFactory.CreateAdmin(    uint           version,     // Version    out MTRetCode   …

**LLM**：**接受**（认为相关），分级 `2 部分支撑`
**理由**：The passage shows the 'admin' parameter as a pointer to the administrator interface, but does not explicitly explain its role as an output parameter returning the created interface.

**填这里**： `[ ]`

---

## 10

**问题**：在 OnTradeRequestUpdate 方法中，request 参数指向的是什么对象？

**Chunk**：[in]  Position of a trade request in an array, starting with 0.  Return Value  Returns a pointer to the detached object of the trade request.  Note  This method removes the pointer to the object at the given position of the array and returns it. The size of the array is decreased by one, and the deleted object is not freed.  ###### Update  Update

**LLM**：拒绝（认为不相关），分级 `1 沾边`
**理由**：The passage mentions a trade request object but does not mention the OnTradeRequestUpdate method, the request parameter, or the IMTRequest type.

**填这里**： `[ ]`

---

## 11

**问题**：在 OnTradeRequestUpdate 方法中，request 参数指向的是什么对象？

**Chunk**：参数  登录名  [in]  删除交易品种的[经理登录名](imtconmanager_login.htm)。如果是通过插件删除交易品种，则该参数指定为0。  cfg  [in]  指向[交易品种对象](imtconsymbol.htm)的指针。  返回值  在没有该事件的处理程序的情况下，返回[MT_RET_OK](retcodes_successful.htm)。  如果事件处理程序返回的代码不同于[MT_RET_OK](retcodes_successful.htm)，那么将不会删除交易品种，且不会将挂钩传递给其他处理程序（包括其他插件）。  注意  挂钩的调用就在从配置库删除记录之前。该挂钩的主要目的是防止不需要的记录删除。  此方法仅可在MetaTrader 5 Server API中有效。

**LLM**：拒绝（认为不相关），分级 `0 无关`
**理由**：The passage discusses symbol deletion parameters and does not mention OnTradeRequestUpdate or the request parameter.

**填这里**： `[ ]`

---

## 12

**问题**：IMTAdminAPI 接口在 MTAdminCreate 中的输出参数起什么作用？

**Chunk**：The MTAdminCreate exported function creates a new instance of the [IMTAdminAPI](imtadminapi.htm) interface and returns a pointer to it.  | | | --- | | MTAPIRES  MTAdminCreate(    UINT           api_version    // API version    IMTAdminAPI**  admin          // A pointer to the pointer to the interface    ) |  Parameters  api_version  [out]  The current version of Manager API supported by the server is passed in this p …

**LLM**：**接受**（认为相关），分级 `3 直接回答`
**理由**：The passage states that MTAdminCreate creates a new instance of the IMTAdminAPI interface and returns a pointer to it, and shows the admin parameter as the pointer to the interface.

**填这里**： `[ ]`

---

## 13

**问题**：在 IMTServerAPI::FeederGet 中，配置数据复制的具体操作是什么？

**Chunk**：| 函数 | 用途 | | --- | --- | | [FeederCreate](imtserverapi_feedercreate.htm) | 创建数据源配置的对象。 | | [FeederModuleCreate](imtserverapi_feedermodulecreate.htm) | 创建数据源模块配置的对象。 | | [FeederParamCreate](imtserverapi_feederparamcreate.htm) | 创建数据源参数的对象。 | | [FeederTranslateCreate](imtserverapi_feedertranslatecreate.htm) | 创建对从数据源传输的信息进行转换的设置对象。 | | [FeederSubscribe](imtserverapi_feedersubscribe.htm) | 订阅与数据源配置相关的事件和挂钩。 | | [Feeder …

**LLM**：拒绝（认为不相关），分级 `1 沾边`
**理由**：The passage lists other feeder-related functions but does not mention FeederGet or the copying of configuration data.

**填这里**： `[ ]`

---

## 14

**问题**：在 OnTradeRequestUpdate 方法中，request 参数指向的是什么对象？

**Chunk**：IMTTradeSink::OnTradeRequestUpdate  交易请求的状态 [已更改的事件的](imtrequest.htm) 处理程序。  | | | --- | | virtual void  IMTTradeSink::OnTradeRequestUpdate(    const IMTRequest*  request      // 指向请求对象的指针    ) |  参数  request  [in]  指向 [交易请求的对象的指针](imtrequest.htm)。  注意  该方法通知交易请求的状态已在其处理期间更改。  若要分析更改，请使用交易请求的 [IMTRequest::ResultRetcode](imtrequest_resultretcode.htm) 属性及其状态的其他属性 (IMTRequest::Result*)。  #### OnTradeRequestDelete  OnTra …

**LLM**：**接受**（认为相关），分级 `3 直接回答`
**理由**：The passage explicitly states that the `request` parameter is a pointer to the trading request object (IMTRequest), directly answering the question.

**填这里**： `[ ]`

---

## 15

**问题**：账户组交易的作用是什么？

**Chunk**：交易的周报告  使用该报告评估您交易者的活动。它按周显示分组的已执行交易的信息。数据可以按组进行筛选。  ![“每周交易”报告](deals_weekly.png "“每周交易”报告")  过滤器  可以过滤为报告请求的数据。在经理端请求报告之前，指定以下参数：  * 组 — 包含账户的组，在该账户上必须创建报告。您可以指定一个或多个用逗号分隔的账户。 * 时段 — 将生成报告的时段的开始和结束日期。  报告中的图表  该报告包括多个分类图表：  * 交易量 — 交易量的分布：总量图和按周的分布情况。 * 盈利交易量 — 盈利交易量的分布情况。 * 亏损交易量 — 亏损交易量的分布情况。 * 盈利额 — 交易盈利的分布情况。 * 亏损额 — 交易亏损的分布情况。 * 盈利交易数 — 盈利交易数量的分布情况。 * 亏损交易数 — 亏损交易数量的分布情况。 * 盈利交易量平均值 — 盈利交易的平均交易量分布。 * 亏损交易量平均值  …

**LLM**：拒绝（认为不相关），分级 `1 沾边`
**理由**：The passage mentions groups and trades in the context of a weekly report, but it does not contain any information about the function of account group trading or the specific APIs mentioned in the reference answer.

**填这里**： `[ ]`

---

## 16

**问题**：交易品种组在假期里允许客户进行哪些操作？

**Chunk**：IMTConHoliday::SymbolNext  根据索引 [从假期](config_symbol.htm) 适用的交易品种列表中获取交易品种。  C++  | | | --- | | LPCWSTR  IMTConHoliday::SymbolNext(    const UINT  pos      // 交易品种的位置    )  const |  .NET (Gateway/Manager API)  | | | --- | | string  CIMTConHoliday.SymbolNext(    uint        pos      // 交易品种的位置    ) |  参数  pos  [in]  列表中交易品种的位置，从 0 开始。  返回值  若成功，其将返回一个指向带有交易品种全名（包括到其的路径）的字符串的指针。否则，其将返回 NULL。  注  指向结果字符串的指针在对象 [IMTConHol …

**LLM**：拒绝（认为不相关），分级 `1 沾边`
**理由**：The passage mentions holidays and trading symbols but does not contain any information about the operations allowed for clients during holidays.

**填这里**： `[ ]`

---

## 17

**问题**：只能在主服务器上运行的应用程序才能添加或更新配置吗？

**Chunk**：只能从主服务器上运行的插件添加或更新配置。对于所有其他插件，将返回响应代码 [MT_RET_ERR_NOTMAIN](retcodes_api.htm) 。  添加前会检查记录的正确性。如果记录有误，则将返回错误代码 [MT_RET_ERR_PARAMS](retcodes_common.htm) 。  ###### HistorySyncDelete  HistorySyncDelete

**LLM**：**接受**（认为相关），分级 `3 直接回答`
**理由**：The passage directly confirms that configurations can only be added or updated from the main server and specifies the error code returned for others.

**填这里**： `[ ]`

---

## 18

**问题**：只能在主服务器上运行的应用程序才能添加或更新配置吗？

**Chunk**：只能从主服务器上运行的插件添加或更新配置。对于所有其他插件，将返回响应代码 [MT_RET_ERR_NOTMAIN](retcodes_api.htm) 。  添加前会检查记录的正确性。如果记录有误，则将返回错误代码 [MT_RET_ERR_PARAMS](retcodes_common.htm) 。  ###### FirewallDelete  FirewallDelete

**LLM**：**接受**（认为相关），分级 `3 直接回答`
**理由**：The passage directly states that configurations can only be added or updated from the main server and mentions the exact error code.

**填这里**： `[ ]`

---

## 19

**问题**：只能在主服务器上运行的应用程序才能添加或更新配置吗？

**Chunk**：只能从主服务器上运行的插件添加或更新配置。对于所有其他插件，将返回响应代码 [MT_RET_ERR_NOTMAIN](retcodes_api.htm) 。  添加前会检查记录的正确性。如果记录有误，则将返回错误代码 [MT_RET_ERR_PARAMS](retcodes_common.htm) 。  ###### SpreadDelete  SpreadDelete

**LLM**：**接受**（认为相关），分级 `3 直接回答`
**理由**：The passage directly states that configurations can only be added or updated from plugins running on the main server, and other plugins will receive the MT_RET_ERR_NOTMAIN error code.

**填这里**： `[ ]`

---

## 20

**问题**：交易品种组在假期里允许客户进行哪些操作？

**Chunk**：1. 客户或交易员通过客户端或经理端下订单。 2. 服务器收到交易请求并验证其数字签名。 3. 服务器将请求添加到初始请求队列中。 4. 一个单独的流执行请求的初步验证。此阶段检查以下内容：  * 1. 请求的整体有效性； 2. 请求中指定的交易品种： + 客户组是否允许交易品种交易； + 请求时间是否在交易时间段内； + 请求时间是否为假期； + 请求时间是否在服务器运行时间内； + 交易品种交易时间是否尚未过期； + 请求是否因没有交易品种报价而尚未超时； + 交易品种是否允许指定的成交类型；* 是否启用了请求已被接收所来自的账户； * 该账户是否允许交易； * 该账户是否未处于只读模式； * 是否有到历史服务器的连接； * 该阶段检查交易品种的价格并收到当前价格； * 检查请求参数： + 交易量； + 价格正常化； + 停止水平的验证； + 对订单数量的限制； + 对订单和持仓总交易量的限制；* 检查是否有足够的预付款。

**LLM**：拒绝（认为不相关），分级 `1 沾边`
**理由**：The passage mentions checking if the request time is a holiday during trade validation, but does not state what operations clients are allowed to perform during holidays.

**填这里**： `[ ]`

---

## 21

**问题**：在 OnTradeRequestUpdate 方法中，request 参数指向的是什么对象？

**Chunk**：Parameters  request  [in]  A pointer to the object of the changed request.  Note  This method is called by the API to notify that a trade request has been modified.  ###### OnRequestDelete  OnRequestDelete

**LLM**：**接受**（认为相关），分级 `2 部分支撑`
**理由**：The passage states that the request parameter is a pointer to the object of the changed request, but it does not mention the specific type IMTRequest.

**填这里**： `[ ]`

---

## 22

**问题**：在 OnTradeRequestUpdate 方法中，request 参数指向的是什么对象？

**Chunk**：Parameters  request  [in]  A pointer to the object of the added request.  Note  This method is called by the API to notify that a new trade request has been added.  ###### OnRequestUpdate  OnRequestUpdate

**LLM**：**接受**（认为相关），分级 `2 部分支撑`
**理由**：The passage mentions that the request parameter is a pointer to the object of the added request, but does not specify the IMTRequest type.

**填这里**： `[ ]`

---

## 23

**问题**：只能在主服务器上运行的应用程序才能添加或更新配置吗？

**Chunk**：只能从主服务器上运行的插件添加或更新配置。对于所有其他插件，将返回响应代码 [MT_RET_ERR_NOTMAIN](retcodes_api.htm) 。  添加前会检查记录的正确性。如果记录有误，则将返回错误代码 [MT_RET_ERR_PARAMS](retcodes_common.htm) 。  ###### GroupDelete  GroupDelete

**LLM**：**接受**（认为相关），分级 `3 直接回答`
**理由**：The passage directly states that configurations can only be added or updated from plugins running on the main server, and returns MT_RET_ERR_NOTMAIN for all others.

**填这里**： `[ ]`

---

## 24

**问题**：只能在主服务器上运行的应用程序才能添加或更新配置吗？

**Chunk**：只能从主服务器上运行的插件添加或更新配置。对于所有其他插件，将返回响应代码 [MT_RET_ERR_NOTMAIN](retcodes_api.htm)。  添加记录之前会检查记录的正确性。如果记录有误，则将返回错误代码[MT_RET_ERR_PARAMS](retcodes_common.htm)。  ###### AutomationDelete  AutomationDelete

**LLM**：**接受**（认为相关），分级 `3 直接回答`
**理由**：The passage directly confirms that configurations can only be added or updated from the main server and specifies the exact error code returned otherwise.

**填这里**： `[ ]`

---

## 填完后的对照表

| # | 你填的 | 对应 human_label |
|---|---|---|
| 任意 | `Y` | `true` |
| 任意 | `N` | `false` |

改完 JSON 后执行：

```bash
.venv/Scripts/python.exe -u scripts/label_golden_chunks.py --input tests/fixtures/golden_test_set_zh_v2.json --import-sample tests/fixtures/labeling_sample_zh.json
```

一致率会写进 `_labeling_metadata.human_agreement_rate`，低于 0.80 会产出告警。