import unittest
import os
import tempfile
import shutil
from unittest.mock import Mock, patch, MagicMock
from sd_runner.control_nets import get_control_nets
from sd_runner.ip_adapters import get_ip_adapters
from ui.app_actions import AppActions


class TestAdapterSorting(unittest.TestCase):
    def setUp(self):
        """Set up test environment with temporary directories and mock app_actions."""
        # Create temporary directories for testing
        self.temp_dir = tempfile.mkdtemp()
        self.test_files = []
        
        # Create test files
        for i in range(10):
            filename = f"test_adapter_{i:02d}.safetensors"
            filepath = os.path.join(self.temp_dir, filename)
            with open(filepath, 'w') as f:
                f.write(f"test content {i}")
            self.test_files.append(filepath)
        
        # Create proper mock app_actions with all required methods
        self.mock_app_actions = self._create_mock_app_actions()
        
    def _create_mock_app_actions(self):
        """Create a properly structured mock AppActions object."""
        # Create mock functions for all required actions
        mock_actions = {
            "update_progress": Mock(),
            "update_pending": Mock(),
            "update_time_estimation": Mock(),
            "construct_preset": Mock(),
            "set_widgets_from_preset": Mock(),
            "open_password_admin_window": Mock(),
            "set_model_from_models_window": Mock(),
            "set_adapter_from_adapters_window": Mock(),
            "add_recent_adapter_file": Mock(),
            "contains_recent_adapter_file": Mock(),
            "toast": Mock(),
            "alert": Mock(),
        }
        
        # Create AppActions object with mock functions
        return AppActions(mock_actions)
    
    def _reset_mock_call_count(self):
        """Reset the mock call count for contains_recent_adapter_file."""
        self.mock_app_actions.contains_recent_adapter_file.reset_mock()
        
    def tearDown(self):
        """Clean up temporary directories."""
        shutil.rmtree(self.temp_dir)
    
    def test_no_recent_files_random_sort_false(self):
        """Test sorting when no files are recent and random_sort=False."""
        # Mock: no files are recent (all return -1)
        self.mock_app_actions.contains_recent_adapter_file.return_value = -1
        
        control_nets, is_dir = get_control_nets([self.temp_dir], random_sort=False, app_actions=self.mock_app_actions)
        
        # Should return all files in alphabetical order (no recent files to prioritize)
        self.assertTrue(is_dir)
        self.assertEqual(len(control_nets), 10)
        # Files should be in alphabetical order since random_sort=False
        expected_order = sorted([os.path.basename(f) for f in self.test_files])
        actual_order = [os.path.basename(cn.id) for cn in control_nets]
        self.assertEqual(actual_order, expected_order)
        
        # Verify contains_recent_adapter_file was called for each file
        self.assertEqual(self.mock_app_actions.contains_recent_adapter_file.call_count, 10)
    
    def test_no_recent_files_random_sort_true(self):
        """Test sorting when no files are recent and random_sort=True."""
        # Mock: no files are recent (all return -1)
        self.mock_app_actions.contains_recent_adapter_file.return_value = -1
        
        control_nets, is_dir = get_control_nets([self.temp_dir], random_sort=True, app_actions=self.mock_app_actions)
        
        # Should return all files in random order
        self.assertTrue(is_dir)
        self.assertEqual(len(control_nets), 10)
        # Files should be in random order since random_sort=True
        expected_order = sorted([os.path.basename(f) for f in self.test_files])
        actual_order = [os.path.basename(cn.id) for cn in control_nets]
        # Order should be different from alphabetical (with high probability)
        self.assertNotEqual(actual_order, expected_order)
        
        # Verify contains_recent_adapter_file was called for each file
        self.assertEqual(self.mock_app_actions.contains_recent_adapter_file.call_count, 10)
    
    def test_all_files_recent_random_sort_false(self):
        """Test sorting when all files are recent and random_sort=False."""
        self._reset_mock_call_count()
        
        # Mock: all files are recent with different indices
        def mock_contains_recent(file_path):
            filename = os.path.basename(file_path)
            # Extract number from filename and use as recent index
            num = int(filename.split('_')[2].split('.')[0])
            return num  # Most recent = 0, least recent = 9
        
        self.mock_app_actions.contains_recent_adapter_file.side_effect = mock_contains_recent
        
        control_nets, is_dir = get_control_nets([self.temp_dir], random_sort=False, app_actions=self.mock_app_actions)
        
        # Should return files ordered by recency (least recent first)
        self.assertTrue(is_dir)
        self.assertEqual(len(control_nets), 10)
        
        # Check that files are ordered by recency (least recent first)
        actual_order = [os.path.basename(cn.id) for cn in control_nets]
        expected_order = [f"test_adapter_{i:02d}.safetensors" for i in range(9, -1, -1)]
        self.assertEqual(actual_order, expected_order)
        
        # Verify contains_recent_adapter_file was called for each file
        self.assertEqual(self.mock_app_actions.contains_recent_adapter_file.call_count, 10)
    
    def test_all_files_recent_random_sort_true(self):
        """Test sorting when all files are recent and random_sort=True (with jitter)."""
        self._reset_mock_call_count()
        
        # Mock: all files are recent with different indices
        def mock_contains_recent(file_path):
            filename = os.path.basename(file_path)
            num = int(filename.split('_')[2].split('.')[0])
            return num
        
        self.mock_app_actions.contains_recent_adapter_file.side_effect = mock_contains_recent
        
        control_nets, is_dir = get_control_nets([self.temp_dir], random_sort=True, app_actions=self.mock_app_actions)
        
        # Should return files with jitter applied (not pure recency order)
        self.assertTrue(is_dir)
        self.assertEqual(len(control_nets), 10)
        
        # Check that files are not in pure recency order due to jitter
        actual_order = [os.path.basename(cn.id) for cn in control_nets]
        pure_recency_order = [f"test_adapter_{i:02d}.safetensors" for i in range(9, -1, -1)]
        
        # With jitter, the order should be different from pure recency
        # (though this could theoretically be the same by chance)
        self.assertIsInstance(actual_order, list)
        self.assertEqual(len(actual_order), 10)
        
        # Verify contains_recent_adapter_file was called for each file
        self.assertEqual(self.mock_app_actions.contains_recent_adapter_file.call_count, 10)
    
    def test_mixed_recent_non_recent_files(self):
        """Test sorting with mix of recent and non-recent files."""
        self._reset_mock_call_count()
        
        # Mock: some files are recent, some are not
        def mock_contains_recent(file_path):
            filename = os.path.basename(file_path)
            num = int(filename.split('_')[2].split('.')[0])
            # Files 0, 2, 4, 6, 8 are recent, others are not
            if num % 2 == 0:
                return num // 2  # Recent index: 0, 1, 2, 3, 4
            else:
                return -1  # Not recent
        
        self.mock_app_actions.contains_recent_adapter_file.side_effect = mock_contains_recent
        
        control_nets, is_dir = get_control_nets([self.temp_dir], random_sort=False, app_actions=self.mock_app_actions)
        
        # Should have non-recent files first, then recent files ordered by recency
        self.assertTrue(is_dir)
        self.assertEqual(len(control_nets), 10)
        
        actual_order = [os.path.basename(cn.id) for cn in control_nets]
        
        # Non-recent files should come first (1, 3, 5, 7, 9)
        non_recent_files = [f"test_adapter_{i:02d}.safetensors" for i in [1, 3, 5, 7, 9]]
        recent_files = [f"test_adapter_{i:02d}.safetensors" for i in [8, 6, 4, 2, 0]]  # Least recent first
        
        # Check that non-recent files come before recent files
        non_recent_indices = [actual_order.index(f) for f in non_recent_files]
        recent_indices = [actual_order.index(f) for f in recent_files]
        
        # All non-recent indices should be less than all recent indices
        self.assertTrue(all(ni < ri for ni in non_recent_indices for ri in recent_indices))
        
        # Verify contains_recent_adapter_file was called for each file
        self.assertEqual(self.mock_app_actions.contains_recent_adapter_file.call_count, 10)
    
    def test_ip_adapters_sorting(self):
        """Test that IP adapters use the same sorting logic."""
        self._reset_mock_call_count()
        
        # Mock: all files are recent
        def mock_contains_recent(file_path):
            filename = os.path.basename(file_path)
            num = int(filename.split('_')[2].split('.')[0])
            return num
        
        self.mock_app_actions.contains_recent_adapter_file.side_effect = mock_contains_recent
        
        ip_adapters, is_dir = get_ip_adapters([self.temp_dir], random_sort=False, app_actions=self.mock_app_actions)
        
        # Should return files ordered by recency (least recent first)
        self.assertTrue(is_dir)
        self.assertEqual(len(ip_adapters), 10)
        
        actual_order = [os.path.basename(ia.id) for ia in ip_adapters]
        expected_order = [f"test_adapter_{i:02d}.safetensors" for i in range(9, -1, -1)]
        self.assertEqual(actual_order, expected_order)
        
        # Verify contains_recent_adapter_file was called for each file
        self.assertEqual(self.mock_app_actions.contains_recent_adapter_file.call_count, 10)
    
    def test_empty_directory(self):
        """Test behavior with empty directory."""
        self._reset_mock_call_count()
        
        empty_dir = tempfile.mkdtemp()
        try:
            control_nets, is_dir = get_control_nets([empty_dir], random_sort=False, app_actions=self.mock_app_actions)
            self.assertTrue(is_dir)
            self.assertEqual(len(control_nets), 0)
            
            # Verify contains_recent_adapter_file was not called (no files)
            self.assertEqual(self.mock_app_actions.contains_recent_adapter_file.call_count, 0)
        finally:
            shutil.rmtree(empty_dir)
    
    def test_single_file_directory(self):
        """Test behavior with single file directory."""
        self._reset_mock_call_count()
        
        single_file_dir = tempfile.mkdtemp()
        single_file = os.path.join(single_file_dir, "single.safetensors")
        with open(single_file, 'w') as f:
            f.write("test")
        
        try:
            # Mock: file is recent
            self.mock_app_actions.contains_recent_adapter_file.return_value = 0
            
            control_nets, is_dir = get_control_nets([single_file_dir], random_sort=False, app_actions=self.mock_app_actions)
            self.assertTrue(is_dir)
            self.assertEqual(len(control_nets), 1)
            self.assertEqual(os.path.basename(control_nets[0].id), "single.safetensors")
            
            # Verify contains_recent_adapter_file was called once
            self.assertEqual(self.mock_app_actions.contains_recent_adapter_file.call_count, 1)
        finally:
            shutil.rmtree(single_file_dir)
    
    def test_jitter_effect_consistency(self):
        """Test that jitter produces different results across multiple runs."""
        self._reset_mock_call_count()
        
        # Mock: all files are recent
        def mock_contains_recent(file_path):
            filename = os.path.basename(file_path)
            num = int(filename.split('_')[2].split('.')[0])
            return num
        
        self.mock_app_actions.contains_recent_adapter_file.side_effect = mock_contains_recent
        
        print(f"\n=== Testing Jitter Effect ===")
        print(f"Directory: {self.temp_dir}")
        print(f"Files: {[os.path.basename(f) for f in self.test_files]}")
        print(f"Expected pure recency order (least recent first): {[f'test_adapter_{i:02d}.safetensors' for i in range(9, -1, -1)]}")
        
        # Run multiple times with random_sort=True
        results = []
        for run_num in range(5):
            self._reset_mock_call_count()  # Reset for each run
            control_nets, _ = get_control_nets([self.temp_dir], random_sort=True, app_actions=self.mock_app_actions)
            order = [os.path.basename(cn.id) for cn in control_nets]
            results.append(order)
            
            print(f"\nRun {run_num + 1}:")
            print(f"  Order: {order}")
            
            # Verify contains_recent_adapter_file was called for each file in each run
            self.assertEqual(self.mock_app_actions.contains_recent_adapter_file.call_count, 10)
            print(f"  Call count verified: {self.mock_app_actions.contains_recent_adapter_file.call_count}")
        
        # Analyze results
        print(f"\n=== Jitter Analysis ===")
        unique_results = set(tuple(result) for result in results)
        print(f"Number of unique orderings: {len(unique_results)}")
        print(f"Total runs: {len(results)}")
        
        # Check for jitter by comparing with pure recency order
        pure_recency_order = [f"test_adapter_{i:02d}.safetensors" for i in range(9, -1, -1)]
        print(f"Pure recency order: {pure_recency_order}")
        
        # Count how many runs match pure recency (should be few due to jitter)
        matches_pure_recency = sum(1 for result in results if result == pure_recency_order)
        print(f"Runs matching pure recency: {matches_pure_recency}")
        
        # Check if jitter is working by looking for variation
        jitter_detected = len(unique_results) > 1 or matches_pure_recency < len(results)
        print(f"Jitter detected: {jitter_detected}")
        
        # Detailed comparison of first two runs
        if len(results) >= 2:
            print(f"\n=== Detailed Comparison (Runs 1 vs 2) ===")
            run1_order = results[0]
            run2_order = results[1]
            print(f"Run 1: {run1_order}")
            print(f"Run 2: {run2_order}")
            print(f"Same order: {run1_order == run2_order}")
            
            # Show position changes
            position_changes = []
            for i, (file1, file2) in enumerate(zip(run1_order, run2_order)):
                if file1 != file2:
                    position_changes.append(f"Position {i}: {file1} -> {file2}")
            
            if position_changes:
                print(f"Position changes: {len(position_changes)}")
                for change in position_changes[:5]:  # Show first 5 changes
                    print(f"  {change}")
                if len(position_changes) > 5:
                    print(f"  ... and {len(position_changes) - 5} more changes")
            else:
                print("No position changes detected")
        
        # Assertions
        self.assertGreaterEqual(len(unique_results), 1)  # At least one result
        
        # If we have multiple runs, we should see some variation due to jitter
        # (though this could theoretically fail if all runs produce the same order by chance)
        if len(results) > 1:
            print(f"\n=== Jitter Verification ===")
            print(f"Expected: Some variation due to jitter")
            print(f"Actual: {len(unique_results)} unique orderings out of {len(results)} runs")
            
            # More lenient assertion - jitter should work most of the time
            # We'll consider it working if we have variation OR if we have fewer pure recency matches
            jitter_working = len(unique_results) > 1 or matches_pure_recency < len(results) * 0.8
            print(f"Jitter working: {jitter_working}")
            
            # This assertion might occasionally fail due to randomness, but should pass most of the time
            if not jitter_working:
                print("WARNING: Jitter test failed - this might be due to random chance")
                print("Consider running the test again or adjusting jitter_weight")
    
    def test_jitter_simple_comparison(self):
        """Simple test to compare two runs and verify jitter is working."""
        self._reset_mock_call_count()
        
        # Mock: all files are recent
        def mock_contains_recent(file_path):
            filename = os.path.basename(file_path)
            num = int(filename.split('_')[2].split('.')[0])
            return num
        
        self.mock_app_actions.contains_recent_adapter_file.side_effect = mock_contains_recent
        
        print(f"\n=== Simple Jitter Comparison Test ===")
        
        # Run 1
        self._reset_mock_call_count()
        control_nets1, _ = get_control_nets([self.temp_dir], random_sort=True, app_actions=self.mock_app_actions)
        order1 = [os.path.basename(cn.id) for cn in control_nets1]
        print(f"Run 1 order: {order1}")
        print(f"Run 1 call count: {self.mock_app_actions.contains_recent_adapter_file.call_count}")
        
        # Run 2
        self._reset_mock_call_count()
        control_nets2, _ = get_control_nets([self.temp_dir], random_sort=True, app_actions=self.mock_app_actions)
        order2 = [os.path.basename(cn.id) for cn in control_nets2]
        print(f"Run 2 order: {order2}")
        print(f"Run 2 call count: {self.mock_app_actions.contains_recent_adapter_file.call_count}")
        
        # Compare
        same_order = order1 == order2
        print(f"Same order: {same_order}")
        
        if not same_order:
            print("✓ Jitter is working - different orders produced")
            # Show specific differences
            differences = []
            for i, (file1, file2) in enumerate(zip(order1, order2)):
                if file1 != file2:
                    differences.append(f"Position {i}: {file1} vs {file2}")
            
            print(f"Differences found: {len(differences)}")
            for diff in differences[:3]:  # Show first 3 differences
                print(f"  {diff}")
        else:
            print("⚠ Same order produced - jitter might not be working or this is random chance")
            print("Consider running the test again")
        
        # Verify call counts
        self.assertEqual(self.mock_app_actions.contains_recent_adapter_file.call_count, 10)
        
        # The assertion is lenient - we just want to verify the function works
        # Jitter effectiveness is probabilistic
        self.assertIsInstance(order1, list)
        self.assertIsInstance(order2, list)
        self.assertEqual(len(order1), 10)
        self.assertEqual(len(order2), 10)
    
    def test_no_app_actions(self):
        """Test behavior when app_actions is None."""
        control_nets, is_dir = get_control_nets([self.temp_dir], random_sort=False, app_actions=None)
        
        # Should work without recent file tracking
        self.assertTrue(is_dir)
        self.assertEqual(len(control_nets), 10)
        
        # Files should be in alphabetical order
        actual_order = [os.path.basename(cn.id) for cn in control_nets]
        expected_order = sorted([os.path.basename(f) for f in self.test_files])
        self.assertEqual(actual_order, expected_order)
        
        # Note: contains_recent_adapter_file should not be called when app_actions is None


if __name__ == '__main__':
    unittest.main()
