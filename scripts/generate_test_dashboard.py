#!/usr/bin/env python
"""
Test Results Dashboard Generator

Generates an interactive HTML dashboard from pytest results, coverage reports, and performance metrics.
This is run after tests complete to visualize results.

Usage:
    python scripts/generate_test_dashboard.py
"""

import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional


class TestDashboardGenerator:
    """Generate HTML dashboard from test results."""
    
    def __init__(self, output_dir: str = "test-results"):
        """Initialize dashboard generator."""
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
        self.test_results = {}
        self.coverage_data = {}
        self.performance_data = {}
        
    def parse_test_results(self, junit_xml_path: str) -> None:
        """Parse JUnit XML test results."""
        if not os.path.exists(junit_xml_path):
            print(f"Warning: JUnit XML not found at {junit_xml_path}")
            return
            
        try:
            tree = ET.parse(junit_xml_path)
            root = tree.getroot()
            
            total_tests = int(root.get("tests", 0))
            failed_tests = int(root.get("failures", 0))
            skipped_tests = int(root.get("skipped", 0))
            passed_tests = total_tests - failed_tests - skipped_tests
            
            self.test_results = {
                "total": total_tests,
                "passed": passed_tests,
                "failed": failed_tests,
                "skipped": skipped_tests,
                "success_rate": (passed_tests / total_tests * 100) if total_tests > 0 else 0,
                "test_suites": []
            }
            
            # Parse individual test suites
            for testsuite in root.findall("testsuite"):
                suite_name = testsuite.get("name", "Unknown")
                suite_tests = int(testsuite.get("tests", 0))
                suite_failures = int(testsuite.get("failures", 0))
                suite_skipped = int(testsuite.get("skipped", 0))
                suite_time = float(testsuite.get("time", 0))
                
                testcases = []
                for testcase in testsuite.findall("testcase"):
                    tc_name = testcase.get("name", "Unknown")
                    tc_time = float(testcase.get("time", 0))
                    tc_status = "passed"
                    tc_message = ""
                    
                    if testcase.find("failure") is not None:
                        tc_status = "failed"
                        tc_message = testcase.find("failure").get("message", "")
                    elif testcase.find("skipped") is not None:
                        tc_status = "skipped"
                        tc_message = testcase.find("skipped").get("message", "")
                    
                    testcases.append({
                        "name": tc_name,
                        "status": tc_status,
                        "time": tc_time,
                        "message": tc_message
                    })
                
                self.test_results["test_suites"].append({
                    "name": suite_name,
                    "tests": suite_tests,
                    "passed": suite_tests - suite_failures - suite_skipped,
                    "failed": suite_failures,
                    "skipped": suite_skipped,
                    "time": suite_time,
                    "testcases": testcases
                })
        except Exception as e:
            print(f"Error parsing JUnit XML: {e}")
    
    def parse_coverage_data(self, coverage_json_path: str) -> None:
        """Parse coverage JSON report."""
        if not os.path.exists(coverage_json_path):
            print(f"Warning: Coverage JSON not found at {coverage_json_path}")
            return
            
        try:
            with open(coverage_json_path) as f:
                data = json.load(f)
            
            # Extract coverage summary
            if "totals" in data:
                totals = data["totals"]
                self.coverage_data = {
                    "total_coverage": totals.get("percent_covered", 0),
                    "lines_covered": totals.get("num_statements", 0),
                    "lines_missing": totals.get("missing_lines", 0),
                    "files": data.get("files", {})
                }
        except Exception as e:
            print(f"Error parsing coverage JSON: {e}")
    
    def parse_performance_data(self, performance_json_path: str) -> None:
        """Parse performance benchmark data."""
        if not os.path.exists(performance_json_path):
            print(f"Warning: Performance data not found at {performance_json_path}")
            return
            
        try:
            with open(performance_json_path) as f:
                self.performance_data = json.load(f)
        except Exception as e:
            print(f"Error parsing performance data: {e}")
    
    def generate_html(self) -> str:
        """Generate HTML dashboard."""
        total_tests = self.test_results.get("total", 0)
        passed = self.test_results.get("passed", 0)
        failed = self.test_results.get("failed", 0)
        skipped = self.test_results.get("skipped", 0)
        success_rate = self.test_results.get("success_rate", 0)
        
        coverage_pct = self.coverage_data.get("total_coverage", 0)
        
        timestamp = datetime.now().isoformat()
        
        # Build test suites HTML
        suites_html = ""
        for suite in self.test_results.get("test_suites", []):
            suite_success = ((suite["passed"] / suite["tests"] * 100) 
                           if suite["tests"] > 0 else 0)
            
            testcases_html = ""
            for tc in suite.get("testcases", []):
                status_class = tc["status"]
                testcases_html += f"""
                <tr class="test-case test-case-{status_class}">
                    <td>{tc['name']}</td>
                    <td><span class="badge badge-{status_class}">{tc['status'].upper()}</span></td>
                    <td>{tc['time']:.3f}s</td>
                    <td>{tc.get('message', '')}</td>
                </tr>
                """
            
            suites_html += f"""
            <div class="suite-card">
                <h3>{suite['name']}</h3>
                <div class="suite-stats">
                    <span class="stat">Passed: <strong>{suite['passed']}</strong></span>
                    <span class="stat">Failed: <strong>{suite['failed']}</strong></span>
                    <span class="stat">Skipped: <strong>{suite['skipped']}</strong></span>
                    <span class="stat">Time: <strong>{suite['time']:.2f}s</strong></span>
                </div>
                <div class="progress-bar">
                    <div class="progress-fill" style="width: {suite_success}%"></div>
                </div>
                <table class="testcases-table">
                    <thead>
                        <tr>
                            <th>Test Name</th>
                            <th>Status</th>
                            <th>Time</th>
                            <th>Message</th>
                        </tr>
                    </thead>
                    <tbody>
                        {testcases_html}
                    </tbody>
                </table>
            </div>
            """
        
        # Build coverage files HTML
        coverage_files_html = ""
        for filepath, file_coverage in self.coverage_data.get("files", {}).items():
            if isinstance(file_coverage, dict) and "summary" in file_coverage:
                coverage_pct = file_coverage["summary"].get("percent_covered", 0)
                coverage_files_html += f"""
                <tr>
                    <td>{filepath}</td>
                    <td><strong>{coverage_pct:.1f}%</strong></td>
                    <td><div class="progress-bar mini"><div class="progress-fill" style="width: {coverage_pct}%"></div></div></td>
                </tr>
                """
        
        # Performance data HTML
        performance_html = ""
        if self.performance_data:
            for metric, value in self.performance_data.items():
                performance_html += f"""
                <tr>
                    <td>{metric}</td>
                    <td><strong>{value}</strong></td>
                </tr>
                """
        
        html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>BugSift Test Results Dashboard</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 20px;
            min-height: 100vh;
        }}
        
        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}
        
        .header {{
            background: white;
            padding: 30px;
            border-radius: 12px;
            margin-bottom: 30px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.2);
        }}
        
        .header h1 {{
            color: #333;
            margin-bottom: 10px;
            font-size: 32px;
        }}
        
        .header p {{
            color: #666;
            font-size: 14px;
        }}
        
        .metrics {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-top: 20px;
        }}
        
        .metric-card {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 8px;
            text-align: center;
            box-shadow: 0 5px 15px rgba(0, 0, 0, 0.1);
        }}
        
        .metric-card.success {{ background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%); }}
        .metric-card.failed {{ background: linear-gradient(135deg, #ee0979 0%, #ff6a00 100%); }}
        .metric-card.warning {{ background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); }}
        
        .metric-value {{
            font-size: 48px;
            font-weight: bold;
            margin-bottom: 5px;
        }}
        
        .metric-label {{
            font-size: 14px;
            opacity: 0.9;
        }}
        
        .section {{
            background: white;
            padding: 30px;
            border-radius: 12px;
            margin-bottom: 30px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.2);
        }}
        
        .section h2 {{
            color: #333;
            margin-bottom: 20px;
            border-bottom: 3px solid #667eea;
            padding-bottom: 10px;
            font-size: 24px;
        }}
        
        .suite-card {{
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            padding: 15px;
            margin-bottom: 15px;
            background: #f9f9f9;
        }}
        
        .suite-card h3 {{
            color: #333;
            margin-bottom: 10px;
            font-size: 18px;
        }}
        
        .suite-stats {{
            display: flex;
            gap: 15px;
            margin-bottom: 10px;
            flex-wrap: wrap;
        }}
        
        .stat {{
            font-size: 13px;
            color: #666;
        }}
        
        .stat strong {{
            color: #333;
        }}
        
        .progress-bar {{
            width: 100%;
            height: 8px;
            background: #e0e0e0;
            border-radius: 4px;
            overflow: hidden;
            margin-bottom: 15px;
        }}
        
        .progress-bar.mini {{
            height: 6px;
            margin-bottom: 0;
        }}
        
        .progress-fill {{
            height: 100%;
            background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
            transition: width 0.3s ease;
        }}
        
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
            margin-top: 10px;
        }}
        
        th {{
            background: #f0f0f0;
            color: #333;
            font-weight: 600;
            padding: 12px;
            text-align: left;
            border-bottom: 2px solid #e0e0e0;
        }}
        
        td {{
            padding: 10px 12px;
            border-bottom: 1px solid #f0f0f0;
        }}
        
        tr:hover {{
            background: #f9f9f9;
        }}
        
        .testcases-table {{
            display: none;
        }}
        
        .suite-card.expanded .testcases-table {{
            display: table;
        }}
        
        .test-case {{
            font-size: 12px;
        }}
        
        .badge {{
            display: inline-block;
            padding: 4px 10px;
            border-radius: 4px;
            font-weight: 600;
            font-size: 11px;
        }}
        
        .badge-passed {{
            background: #d4edda;
            color: #155724;
        }}
        
        .badge-failed {{
            background: #f8d7da;
            color: #721c24;
        }}
        
        .badge-skipped {{
            background: #fff3cd;
            color: #856404;
        }}
        
        .test-case-failed {{
            background-color: #fff5f5 !important;
        }}
        
        .footer {{
            text-align: center;
            color: white;
            padding: 20px;
            font-size: 12px;
        }}
        
        @media (max-width: 768px) {{
            .metrics {{
                grid-template-columns: 1fr;
            }}
            
            table {{
                font-size: 11px;
            }}
            
            .metric-value {{
                font-size: 32px;
            }}
        }}
    </style>
    <script>
        function toggleSuite(element) {{
            element.classList.toggle('expanded');
        }}
        
        document.addEventListener('DOMContentLoaded', function() {{
            document.querySelectorAll('.suite-card').forEach(card => {{
                card.addEventListener('click', function() {{
                    toggleSuite(this);
                }});
            }});
        }});
    </script>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🧪 BugSift Test Results Dashboard</h1>
            <p>Test execution completed at {timestamp}</p>
            
            <div class="metrics">
                <div class="metric-card success">
                    <div class="metric-value">{total_tests}</div>
                    <div class="metric-label">Total Tests</div>
                </div>
                <div class="metric-card success">
                    <div class="metric-value">{passed}</div>
                    <div class="metric-label">Passed</div>
                </div>
                <div class="metric-card {'failed' if failed > 0 else 'success'}">
                    <div class="metric-value">{failed}</div>
                    <div class="metric-label">Failed</div>
                </div>
                <div class="metric-card warning">
                    <div class="metric-value">{skipped}</div>
                    <div class="metric-label">Skipped</div>
                </div>
                <div class="metric-card">
                    <div class="metric-value">{success_rate:.1f}%</div>
                    <div class="metric-label">Success Rate</div>
                </div>
                <div class="metric-card">
                    <div class="metric-value">{coverage_pct:.1f}%</div>
                    <div class="metric-label">Coverage</div>
                </div>
            </div>
        </div>
        
        <div class="section">
            <h2>📊 Test Suites</h2>
            {suites_html}
        </div>
        
        <div class="section">
            <h2>📈 Code Coverage</h2>
            <table>
                <thead>
                    <tr>
                        <th>File</th>
                        <th>Coverage %</th>
                        <th>Progress</th>
                    </tr>
                </thead>
                <tbody>
                    {coverage_files_html if coverage_files_html else '<tr><td colspan="3">No coverage data available</td></tr>'}
                </tbody>
            </table>
        </div>
        
        {'<div class="section"><h2>⚡ Performance Metrics</h2><table><thead><tr><th>Metric</th><th>Value</th></tr></thead><tbody>' + performance_html + '</tbody></table></div>' if performance_html else ''}
        
        <div class="footer">
            <p>Generated by BugSift Test Dashboard • {timestamp}</p>
        </div>
    </div>
</body>
</html>
        """
        return html
    
    def save_dashboard(self, output_file: str = "index.html") -> str:
        """Save dashboard HTML to file."""
        output_path = self.output_dir / output_file
        html = self.generate_html()
        
        with open(output_path, "w") as f:
            f.write(html)
        
        print(f"✅ Dashboard generated: {output_path}")
        return str(output_path)


def main():
    """Generate test dashboard from pytest results."""
    import sys
    
    # Check if we're in the right directory
    backend_dir = Path.cwd()
    if not (backend_dir / "pyproject.toml").exists():
        print("Error: Please run this from the backend directory")
        sys.exit(1)
    
    generator = TestDashboardGenerator(output_dir="test-results")
    
    # Parse results
    generator.parse_test_results("test-results/junit.xml")
    generator.parse_coverage_data("test-results/coverage.json")
    generator.parse_performance_data("test-results/performance.json")
    
    # Generate dashboard
    dashboard_path = generator.save_dashboard()
    
    print(f"\n📊 Dashboard ready at: {dashboard_path}")
    print(f"Open in browser: file://{Path(dashboard_path).absolute()}")


if __name__ == "__main__":
    main()
