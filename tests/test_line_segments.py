"""Known-site checks for local bends; no Sinhala or saved-page labels."""
import unittest
import numpy as np
from services.line_refinement import refine_lines, line_sites, _valid_model


class SegmentRefinementTests(unittest.TestCase):
    def test_local_bends_improve_unfitted_dots_without_changing_identity(self):
        ids = np.array([(c,col,line,row) for line in range(3) for c in range(28)
                        for col in range(2) for row in range(3)])
        ci,col,li,row = ids.T
        ratio = 2.6
        q = ci*ratio+col
        def coarse(q,rows,line):
            return np.column_stack([100+15*q,100+60*line+15*rows])
        points = np.column_stack([100+15*q,100+60*li+15*row]).astype(float)
        points[:,1] += 2.7*np.sin(2*np.pi*(q-q.min())/np.ptp(q)*2)
        train = np.arange(len(points))%5 != 0
        args = (points,ci,col,li,row,np.ones(len(points),bool),train,
                np.array([ratio,4.]),np.array([15.,15.]),.28,coarse)
        old = refine_lines(*args)
        new = refine_lines(*args,refine_segments=True)
        self.assertIsNotNone(old)
        self.assertIsNotNone(new)
        np.testing.assert_array_equal(np.column_stack([new[k] for k in ('ci','col','li','row')]),ids)
        self.assertTrue(np.all(new['good']))
        old_loss = np.mean(old['ex'][~train]**2+old['ey'][~train]**2)
        new_loss = np.mean(new['ex'][~train]**2+new['ey'][~train]**2)
        self.assertLess(new_loss,old_loss*.8)
        self.assertTrue(any('bend_knots' in m for m in new['models'].values()))

    def test_folded_segment_is_rejected(self):
        model = dict(center=0,scale=1,coefficients=[[100,115],[15,0],[0,0],[0,0],[0,15],[0,0]],
                     bend_knots=[0,1,2],bend_offsets=[[0,0],[-30,0],[0,0]])
        self.assertFalse(_valid_model(model,np.array([15.,15.]),0,2))

    def test_old_serialized_models_still_work(self):
        model = dict(center=0,scale=1,coefficients=[[100,115],[15,0],[0,0],[0,0],[0,15],[0,0]])
        np.testing.assert_allclose(line_sites(np.array([0,1]),np.array([0,2]),model),[[100,100],[115,130]])


if __name__ == '__main__':
    unittest.main()
