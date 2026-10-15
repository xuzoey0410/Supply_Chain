# 参与贡献

使用 Python 3.13 创建虚拟环境并安装 `requirements.txt`。提交前运行：

```bash
python -m unittest discover -s . -p 'test_*.py' -v
python evaluation.py
```

请使用 `demo_data.py` 或测试夹具中的虚构数据复现问题，不提交真实业务表、API Key、对话记录或 `.local`。

新增业务能力应先在确定性服务层实现，再添加工具契约和执行边界，最后接入 UI。修改算法时需要说明单位、缺口口径与对旧方案的影响；保持页面与工具使用同一事实来源。

真实模型评估使用自己的密钥，会产生费用；离线 CI 不调用模型。不要将小样本的离线状态检查结果表述为真实模型准确率。
