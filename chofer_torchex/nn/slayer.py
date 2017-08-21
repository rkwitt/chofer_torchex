import torch
from torch import Tensor, LongTensor
from torch.tensor import _TensorBase
from torch.autograd import Variable
from torch.nn.parameter import Parameter
from torch.nn.modules.module import Module


def safe_tensor_size(tensor, dim):
    try:
        return tensor.size(dim)

    except Exception:
        return 0


class SLayer(Module):
    def __init__(self, n_elements, point_dimension=2,
                 centers_init=None,
                 sharpness_init=None):
        super(SLayer, self).__init__()

        self.n_elements = n_elements
        self.point_dimension = point_dimension

        if centers_init is None:
            centers_init = torch.rand(self.n_elements, self.point_dimension)

        if sharpness_init is None:
            sharpness_init = torch.ones(self.n_elements, self.point_dimension)*3

        self.centers = Parameter(centers_init)
        self.sharpness = Parameter(sharpness_init)

    @staticmethod
    def prepare_batch(batch: [Tensor], point_dim, gpu=False)->tuple:
        assert not any(t.is_cuda for t in batch)

        batch_size = len(batch)
        batch_max_points = max([safe_tensor_size(t, 0) for t in batch])
        input_type = type(batch[0])

        if batch_max_points == 0:
            # if we are here, batch consists only of empty diagrams.
            batch_max_points = 1

        # This will later be used to set the dummy points to zero in the output.
        not_dummy_points = input_type(batch_size, batch_max_points)
        # In the initialization every point is a dummy point.
        not_dummy_points[:, :] = 0

        prepared_batch = []

        for i, multi_set in enumerate(batch):
            n_points = safe_tensor_size(multi_set, 0)

            prepared_dgm = type(multi_set)()
            torch.zeros(batch_max_points, point_dim, out=prepared_dgm)

            if n_points > 0:
                index_selection = LongTensor(range(n_points))
                if prepared_dgm.is_cuda:
                    index_selection = index_selection.cuda()

                prepared_dgm.index_add_(0, index_selection, multi_set)

                not_dummy_points[i, :n_points] = 1

            prepared_batch.append(prepared_dgm)

        prepared_batch = torch.stack(prepared_batch)

        if gpu:
            not_dummy_points = not_dummy_points.cuda()
            prepared_batch = prepared_batch.cuda()

        return prepared_batch, not_dummy_points, batch_max_points, batch_size

    @staticmethod
    def is_prepared_batch(input):
        if not (isinstance(input, tuple) and len(input) == 4):
            return False

        else:
            batch, not_dummy_points, max_points, batch_size = input
            return isinstance(batch, _TensorBase) and isinstance(not_dummy_points, _TensorBase) and max_points > 0 and batch_size > 0

    @staticmethod
    def is_list_of_tensors(input):
        return all([isinstance(x, _TensorBase) for x in input])

    @property
    def is_gpu(self):
        return self.centers.is_cuda

    def forward(self, input)->Variable:
        batch, not_dummy_points, max_points, batch_size = None, None, None, None

        if self.is_prepared_batch(input):
            batch, not_dummy_points, max_points, batch_size = input
        elif self.is_list_of_tensors(input):
            batch, not_dummy_points, max_points, batch_size = SLayer.prepare_batch(input,
                                                                                   self.point_dimension,
                                                                                   gpu=self.is_gpu)

        else:
            raise ValueError('SLayer does not recognize input format! Expecting [Tensor] or prepared batch.')

        batch = Variable(batch, requires_grad=False)
        batch = torch.cat([batch] * self.n_elements, 1)

        not_dummy_points = Variable(not_dummy_points, requires_grad=False)
        not_dummy_points = torch.cat([not_dummy_points] * self.n_elements, 1)
        not_dummy_points = not_dummy_points.view(batch_size, self.n_elements * max_points, 1)

        centers = torch.cat([self.centers] * max_points, 1)
        centers = centers.view(-1, self.point_dimension)
        centers = torch.stack([centers] * batch_size, 0)

        sharpness = torch.cat([self.sharpness] * max_points, 1)
        sharpness = sharpness.view(-1, self.point_dimension)
        sharpness = torch.stack([sharpness] * batch_size, 0)

        x = centers - batch
        x = x.pow(2)
        x = torch.mul(x, sharpness)
        x = torch.sum(x, 2)
        x = torch.exp(-x)
        x = torch.mul(x, not_dummy_points)
        x = x.view(batch_size, self.n_elements, -1)
        x = torch.sum(x, 2)
        x = x.squeeze()

        return x

    def __str__(self):
        return 'SLayer (... -> {} )'.format(self.n_elements)