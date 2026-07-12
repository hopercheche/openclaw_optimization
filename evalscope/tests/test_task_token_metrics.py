import unittest

from evalscope.agent.external.adapter import _to_model_output
from evalscope.api.messages import PerformanceMetrics
from evalscope.api.model import ModelUsage
from evalscope.evaluator.perf_collector import PerfCollector
from evalscope.report.combinator import gen_table, get_task_token_summary
from evalscope.report.report import Category, Metric, Report, Subset


class TaskTokenMetricsTest(unittest.TestCase):

    def test_task_usage_aggregates_after_request_usage(self):
        collector = PerfCollector()
        collector.record(
            PerformanceMetrics(latency=1.0, input_tokens=10, output_tokens=5),
            sample_index=('subset-a', '0', 'group'),
            turn_index=0,
        )
        collector.record(
            PerformanceMetrics(latency=2.0, input_tokens=20, output_tokens=10),
            sample_index=('subset-a', '0', 'group'),
            turn_index=1,
        )
        collector.record_task_usage(
            input_tokens=30,
            output_tokens=15,
            sample_index=('subset-a', '0', 'group'),
        )
        collector.record_task_usage(
            input_tokens=4,
            output_tokens=3,
            sample_index=('subset-b', '0', 'group'),
        )

        summary = collector.get_summary()

        self.assertEqual(summary.task_usage['n_tasks'], 2)
        self.assertEqual(summary.task_usage['total_tokens_count'], 52)
        self.assertEqual(summary.task_usage['total_tokens']['mean'], 26)
        self.assertEqual(summary.task_usage['total_tokens']['min'], 7)
        self.assertEqual(summary.task_usage['total_tokens']['max'], 45)

    def test_external_output_carries_aggregate_task_usage(self):
        output = _to_model_output(
            'done',
            model_name='demo',
            usage=ModelUsage(input_tokens=30, output_tokens=15, total_tokens=999),
            latency=3.5,
        )

        self.assertEqual(output.usage.total_tokens, 45)
        self.assertEqual(output.metadata['task_usage']['total_tokens'], 45)
        self.assertEqual(output.perf_metrics.input_tokens, 30)
        self.assertEqual(output.perf_metrics.output_tokens, 15)

    def test_score_table_contains_compact_task_token_columns(self):
        collector = PerfCollector()
        collector.record_task_usage(input_tokens=30, output_tokens=15, sample_index=('a', '0', 'g'))
        collector.record_task_usage(input_tokens=4, output_tokens=3, sample_index=('b', '0', 'g'))
        report = Report(
            name='demo@sample',
            dataset_name='sample',
            model_name='demo',
            metrics=[
                Metric(
                    name='mean_acc',
                    categories=[
                        Category(
                            name=('default', ),
                            subsets=[Subset(name='default', score=1.0, num=2)],
                        )
                    ],
                )
            ],
            perf_metrics={'summary': collector.get_summary().to_dict()},
        )

        self.assertEqual(
            get_task_token_summary(report),
            {'total_tokens': 52, 'avg_tokens': 26, 'min_tokens': 7, 'max_tokens': 45},
        )
        table = gen_table(report_list=[report])
        for heading in ('Total Tok', 'Avg Tok/Task', 'Min Tok/Task', 'Max Tok/Task'):
            self.assertIn(heading, table)


if __name__ == '__main__':
    unittest.main()
