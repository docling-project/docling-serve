from common import autoscaling_client
# https://aws.amazon.com/blogs/machine-learning/configuring-autoscaling-inference-endpoints-in-amazon-sagemaker/


GPU_THRESHOLD = 70.0 # target 70% GPU utilization
SCALE_IN_COOLDOWN = 600 # scale in after 10 minutes below metric threshold
SCALE_OUT_COOLDOWN = 60 # scale out after 1 minute of above metric threshold
MIN_CAPACITY = 1
MAX_CAPACITY = 2


def has_autoscaling(endpoint_name):
    resource_id = 'endpoint/' + endpoint_name + '/variant/AllTraffic'
    response = autoscaling_client.describe_scalable_targets(
        ServiceNamespace='sagemaker',
        ResourceIds=[resource_id],
        ScalableDimension='sagemaker:variant:DesiredInstanceCount')
    return len(response['ScalableTargets']) > 0


def create_autoscaling(endpoint_name):
    if has_autoscaling(endpoint_name):
        print('Autoscaling already configured for endpoint: ' + endpoint_name)
        return

    resource_id = 'endpoint/' + endpoint_name + '/variant/AllTraffic'
    print('Registering scalable target for endpoint: ' + endpoint_name)

    autoscaling_client.register_scalable_target(
        ServiceNamespace='sagemaker',
        ResourceId=resource_id,
        ScalableDimension='sagemaker:variant:DesiredInstanceCount',
        MinCapacity=MIN_CAPACITY,
        MaxCapacity=MAX_CAPACITY)

    # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/application-autoscaling/client/put_scaling_policy.html
    autoscaling_client.put_scaling_policy(
        PolicyName='GPUUtil-ScalingPolicy',
        ServiceNamespace='sagemaker',
        ResourceId=resource_id,
        ScalableDimension='sagemaker:variant:DesiredInstanceCount',
        PolicyType='TargetTrackingScaling',
        TargetTrackingScalingPolicyConfiguration={
            'TargetValue': GPU_THRESHOLD,
            'CustomizedMetricSpecification':
            {
                'MetricName': 'GPUUtilization',
                'Namespace': '/aws/sagemaker/Endpoints',
                'Dimensions': [
                    {'Name': 'EndpointName', 'Value': endpoint_name },
                    {'Name': 'VariantName','Value': 'AllTraffic'}
                ],
                'Statistic': 'Average',
                'Unit': 'Percent'
            },
            'ScaleInCooldown': SCALE_IN_COOLDOWN,
            'ScaleOutCooldown': SCALE_OUT_COOLDOWN
        })

    print('Autoscaling configured for endpoint: ' + endpoint_name)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Create autoscaling for a SageMaker endpoint')
    parser.add_argument('--endpoint-name', type=str, required=True,
                        help='Name of the endpoint to add autoscaling to')
    args = parser.parse_args()
    create_autoscaling(args.endpoint_name)
