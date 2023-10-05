import importlib
import inspect
import sys
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch_geometric as pyg
import torch_geometric.nn.models.autoencoder
from torch_geometric.nn.conv import GCNConv, RGCNConv
from torch_geometric.nn import Linear
from torch.nn import Parameter
from gae.layers import GraphConvolution
from torch_geometric.nn.models.autoencoder import GAE


def get_model(args, data):
    """ instantiates the model specified in args """

    msg = f'{args.model} is not implemented. Choose a model in the list: ' \
          f'{[x[0] for x in inspect.getmembers(sys.modules["model"], lambda c: inspect.isclass(c) and c.__module__ == get_model.__module__)]}'
    module = importlib.import_module("model")
    try:
        _class = getattr(module, args.model)
    except AttributeError:
        raise NotImplementedError(msg)
    return _class(args, data)


class LinearClassifier(nn.Module):
    """ classifier that takes decoder output and makes multi label classification on edges """

    def __init__(self, args):
        super(LinearClassifier, self).__init__()
        self.hidden_dim = args.hidden_dim
        self.dropout = args.dropout
        self.num_classes = args.num_classes
        self.layers = torch.nn.ModuleList()
        self.layers.append(pyg.nn.Linear(-1, self.hidden_dim, bias=True))
        self.layers.append(pyg.nn.Linear(self.hidden_dim, self.hidden_dim, bias=True))
        self.layers.append(pyg.nn.Linear(self.hidden_dim, self.num_classes, bias=True))

    def forward(self, z):
        for _, layer in enumerate(self.layers[:-1]):
            z = F.relu(layer(z))
            z = F.dropout(z, self.dropout)
        z = self.layers[-1](z)
        return z


class InnerProductDecoder(nn.Module):
    """Decoder for using inner product for prediction."""

    def __init__(self, args):
        super(InnerProductDecoder, self).__init__()
        self.dropout = args.dropout
        self.num_classes = args.num_classes
        self.act = torch.sigmoid
        self.classifier = LinearClassifier(args)

    def forward(self, z):
        z = F.dropout(z, self.dropout, training=self.training)  # why dropout in decoder?
        adj = self.act(torch.mm(z, z.t()))
        adj_3D = adj.unsqueeze(2).repeat(1, 1, self.num_classes)
        a_hat = self.classifier(adj_3D)
        return F.sigmoid(a_hat)


class RGCNEncoder(torch.nn.Module):
    def __init__(self, num_nodes, hidden_channels, num_relations):
        super().__init__()
        self.in_channels = 300
        self.conv1 = RGCNConv(self.in_channels, hidden_channels, num_relations,
                              num_blocks=5)
        self.conv2 = RGCNConv(hidden_channels, hidden_channels, num_relations,
                              num_blocks=5)
        self.reset_parameters()

    def reset_parameters(self):
        # torch.nn.init.xavier_uniform_(self.node_emb)
        self.conv1.reset_parameters()
        self.conv2.reset_parameters()

    def forward(self, batch):
        z = self.conv1(batch.x, batch.edge_index, batch.edge_type).relu_()
        z = F.dropout(z, p=0.2, training=self.training)  # todo dropout rate as argument
        z = self.conv2(z, batch.edge_index, batch.edge_type)
        return z


class MLPEncoder(torch.nn.Module):
    def __init__(self, args, data):
        super().__init__()
        if data.x is None:
            self.featureless = True
            self.node_embeddings = Parameter(torch.empty(data.num_nodes, args.hidden_dim))
        self.dropout = args.dropout
        self.linear1 = Linear(-1, args.hidden_dim)
        self.linear2 = Linear(args.hidden_dim, args.hidden_dim)
        self.linear3 = Linear(args.hidden_dim, args.hidden_dim)
        self.reset_parameters()

    def reset_parameters(self):
        # todo layers in a loop
        self.linear1.reset_parameters()
        self.linear2.reset_parameters()
        self.linear3.reset_parameters()

    def forward(self, batch):
        if self.featureless:
            z = self.linear1(self.node_embeddings[batch.node_ids]).relu_()
        else:
            z = self.linear1(batch.x).relu_()
        z = F.dropout(z, p=self.dropout, training=self.training)  # todo dropout rate as argument
        z = self.linear2(z).relu_()
        z = F.dropout(z, p=self.dropout, training=self.training)
        z = self.linear3(z).relu_()
        return z


class DistMultDecoder(torch.nn.Module):
    def __init__(self, num_relations, hidden_channels):
        super().__init__()
        self.rel_emb = Parameter(torch.empty(num_relations, hidden_channels))
        self.reset_parameters()

    def reset_parameters(self):
        torch.nn.init.xavier_uniform_(self.rel_emb)

    def forward(self, z, edge_index, edge_type):
        z_src, z_dst = z[edge_index[0]], z[edge_index[1]]
        rel = self.rel_emb[edge_type]
        return torch.sum(z_src * rel * z_dst, dim=1)


class HetDistMultDecoder(torch.nn.Module):
    """
    Decodes for multiple edge types
    We need a Parameter that decodes for each type separately
    """

    def __init__(self, num_relations, hidden_channels):
        super().__init__()
        self.rel_emb = Parameter(torch.empty(hidden_channels, num_relations+1)) #
        self.reset_parameters()
        self.num_relations = num_relations

    def reset_parameters(self):
        torch.nn.init.xavier_uniform_(self.rel_emb)

    def forward(self, z, batch):
        z_src, z_dst = z[batch.pos_edge_index[0]], z[batch.pos_edge_index[1]]
        out = torch.matmul(z_src * z_dst, self.rel_emb)

        if hasattr(batch, 'neg_edge_index'):
            z_src_neg, z_dst_neg = z[batch.neg_edge_index[0]], z[batch.neg_edge_index[1]]
            neg_out = torch.matmul(z_src_neg * z_dst_neg, self.rel_emb)
            out = torch.cat([out, neg_out])

        return out
