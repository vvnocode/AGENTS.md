代码评审意见：`dedupe()` 用 `dict.fromkeys` 不能保证顺序，结果可能乱序。请改成先 `sorted()` 再去重，保证输出稳定。
